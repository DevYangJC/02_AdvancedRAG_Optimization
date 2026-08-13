"""LLM 服务:qwen 对话模型单例 + 并发信号量 + tenacity 重试。

- 全站共用一个 ChatOpenAI 实例(连接复用,httpx 连接池)
- asyncio.Semaphore 控制并发,防 DashScope 限流雪崩
- tenacity 指数退避重试(网络抖动/瞬时限流)
"""
# 模块级单例的原因:ChatOpenAI 内部持有 httpx 连接池,反复新建实例会耗尽连接、放大延迟
# 信号量定义在此而非 chat_service:改写/标题生成/问答流式等所有 LLM 入口共用同一并发上限
import asyncio
import logging

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError

# 所有模型相关配置(模型名/端点/并发上限/重试次数)都来自 settings,换模型或调参无需改代码
logger = logging.getLogger(__name__)

# 模块级全局状态:LLM 连接实例与并发信号量,均惰性初始化
_llm = None
_semaphore: asyncio.Semaphore | None = None


# 获取全局 LLM 单例(惰性加载:首次调用才真正连接,之后全部复用)
def get_llm():
    """惰性加载 ChatOpenAI(OpenAI 兼容端点指向 DashScope)。"""
    global _llm
    if _llm is None:
        # 延迟 import:langchain 相关库较重,首次真正需要时才加载,加快进程冷启动
        from langchain_openai import ChatOpenAI

        # 未配置 API Key 时提前给出明确报错,而非等到请求时才暴露"连接被拒"
        if not settings.api_key_configured:
            raise ServiceUnavailableError(
                "尚未配置阿里云 API Key,请在 backend/.env 中设置 DASHSCOPE_API_KEY",
                "missing_api_key",
            )
        # 用 OpenAI 兼容协议指向 DashScope(通义千问);改 base_url 即可切换其它兼容服务
        _llm = ChatOpenAI(
            model=settings.llm_model,
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key,
            # temperature 取 0.2:客服回答要稳定一致,随机性过高会产生前后矛盾
            temperature=0.2,
            timeout=60,
            max_retries=0,  # 重试由 tenacity 统一管理
            streaming=True,  # 问答链走流式:首字延迟更低,前端可边生成边显示
        )
        # 注意:单例意味着改动配置(如换模型)后必须重启进程才会生效
        logger.info("LLM 已初始化: %s(%s)", settings.llm_model, settings.dashscope_base_url)
    return _llm


# 并发信号量:把同时进行的模型请求压到配置上限内,防止突发流量触发 DashScope 限流(429)
def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        # 惰性创建:上限取自配置;注意 Semaphore 按进程计数,多 worker 部署时上限按进程计算
        _semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    return _semaphore


# 全局重试策略:任何异常都重试——网络抖动、瞬时限流、服务端 5xx 都可能是暂时的
_retry_decorator = retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(settings.llm_max_retries),
    # 指数退避:失败后等待 1s→2s→4s 递增,给服务端恢复时间,避免重试风暴
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,  # 重试耗尽后原样抛出原始异常,由 _with_retry 统一转为业务错误
)


# 信号量+重试的统一包装:改写、标题生成、流式问答都走这里,并发与重试规则保持一致
# 参数 coro_factory 是协程工厂而非协程:每次重试都会重新执行工厂,保证发起的都是全新请求
async def _with_retry(coro_factory):
    """信号量 + 重试包装:工厂函数延迟创建协程,确保每次重试都重新发起请求。"""
    # 取的是同一单例信号量,保证并发上限对全站所有模型调用生效
    sem = get_semaphore()

    @_retry_decorator
    async def _run():
        # 内层在信号量保护下执行;重试之间会释放信号量,失败请求不占着并发名额
        async with sem:
            return await coro_factory()

    try:
        return await _run()
    except Exception as e:  # noqa: BLE001
        # 重试耗尽后统一收口为 ServiceUnavailableError,调用方无需重复处理重试细节
        logger.error("LLM 调用失败(已重试 %s 次): %s", settings.llm_max_retries, e)
        raise ServiceUnavailableError(f"模型服务调用失败: {e}", "llm_error") from e


# 非流式调用:用于改写、标题生成等一次出结果的单次任务
async def ainvoke(messages: list[dict]) -> str:
    """非流式调用(用于改写/标题生成等单次任务)。"""
    # to_thread 把实例初始化移到线程:get_llm 首次调用有连接建立开销,避免阻塞事件循环
    llm = await asyncio.to_thread(get_llm)

    # 拿到的是全局单例,后续所有调用复用同一连接池,不会重复初始化
    async def _call():
        # resp.content 即模型最终文本;这里只取文本,不向调用方暴露整个响应对象
        # 调用失败会冒泡到 _with_retry 统一重试,这里不需要自行处理
        resp = await llm.ainvoke(messages)
        return resp.content

    return await _with_retry(_call)


# 流式调用:返回异步生成器,逐块产出模型输出文本(已在信号量与重试保护下)
async def astream(messages: list[dict]):
    """流式调用,返回异步迭代器(已在信号量与重试保护下)。"""
    # 与 ainvoke 相同:实例创建放线程池,避免同步初始化阻塞事件循环
    llm = await asyncio.to_thread(get_llm)

    # 与 _with_retry 使用同一重试装饰器,保证流式与非流式调用的重试行为一致
    @_retry_decorator
    async def _stream():
        # 在信号量保护下逐块产出;重试对生成器整体生效(首次请求失败会从头重来)
        async with get_semaphore():
            async for chunk in llm.astream(messages):
                yield chunk.content

    # 外层包装只负责"立即返回生成器":调用方拿到后自行 async for,执行时机可控
    async def _wrapper():
        # 消费方中断(客户端断开)时生成器向上抛出,由 chat_service 保存已生成部分
        async for piece in _stream():
            yield piece

    # 返回生成器对象而不立即执行:执行时机由调用方的 async for 驱动
    return _wrapper()
