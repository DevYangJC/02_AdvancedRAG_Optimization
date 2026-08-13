"""云端重排序:通义 gte-rerank-v2(DashScope 原生 rerank API)。

DashScope 的 rerank 接口无 langchain 现成组件,这里自封装轻量客户端:
- 共享 httpx.AsyncClient 单例(连接复用)
- 对 (query, 文档) 列表打分,返回按分数降序的 [(index, score)]
- 重试 2 次(指数退避)
"""
# 为什么需要 rerank(重排序):向量相似度对语义偶有误判,重排用更强的专用模型精排,纠正召回顺序
# 只对外暴露 rerank 一个函数:调用方无需关心 HTTP 细节与重试逻辑
# 为什么自封装而非用 langchain 现成组件:DashScope 的 rerank 接口没有官方 langchain 实现
import asyncio
import logging

import httpx

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

_client: httpx.AsyncClient | None = None


# 共享 httpx 客户端单例:连接复用,避免每次重排都重新 TLS 握手
def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        # 请求头直接带 Bearer 认证:与 LLM/embedding 共用同一把 DashScope key
        # timeout=30 秒:重排输入是短文本,响应快,超时上限可以放宽
        _client = httpx.AsyncClient(timeout=30, headers={"Authorization": f"Bearer {settings.dashscope_api_key}"})
    return _client


# 对候选文档重排:query=查询问题、documents=候选文本列表、top_n 可选(返回条数);返回 [(index, score)]
# 返回值按分数降序:调用方直接按顺序取用即可,无需再次排序
async def rerank(query: str, documents: list[str], top_n: int | None = None) -> list[tuple[int, float]]:
    """对候选文档重排;返回 [(index, score)] 按分数降序。"""
    # top_n 可空:缺省由服务端返回全量排序,调用方自行截取
    if not documents:
        # 空候选直接返回:避免一次无效的付费 API 调用
        return []
    if not settings.api_key_configured:
        # 与 LLM 侧一致:未配置密钥时给出统一提示,而不是报"连接失败"
        raise ServiceUnavailableError("尚未配置阿里云 API Key,请在 backend/.env 中设置 DASHSCOPE_API_KEY", "missing_api_key")

    # DashScope 原生 rerank API 格式:model + input{query, documents} + parameters{top_n}
    payload: dict = {
        "model": settings.reranker_model,
        "input": {"query": query, "documents": documents},
        "parameters": {"top_n": top_n} if top_n else {},
    }

    # documents 通常来自向量召回后的候选:这里只负责打分排序,不关心候选怎么来的
    client = _get_client()
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            resp = await client.post(settings.rerank_api_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # DashScope 响应结构: {"output": {"results": [{"index", "relevance_score"}]}}
            # index 对应输入 documents 的下标:调用方据此反查原始候选
            output = data.get("output") or {}
            results = output.get("results") or []
            # relevance_score 范围 [0,1],越大越相关,可直接用于排序展示
            return [(r["index"], r.get("relevance_score", 0.0)) for r in results]
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code == 429:
                # 429 限流:指数退避等待(2^attempt 秒)后重试;立即重试大概率再撞限流
                await asyncio.sleep(2**attempt)
                continue
            # 其它 4xx/5xx 不重试:重试也大概率失败,直接抛出业务错误
            raise ServiceUnavailableError(f"重排序服务失败: {e}", "rerank_error") from e
        except httpx.HTTPError as e:
            # 网络类异常(连接断/超时)可能是瞬时的,退避后重试
            last_exc = e
            await asyncio.sleep(2**attempt)

    # 两轮重试耗尽:统一收口为 ServiceUnavailableError,调用方只需处理一种错误
    logger.error("重排序调用失败(已重试): %s", last_exc)
    raise ServiceUnavailableError(f"重排序服务调用失败: {last_exc}", "rerank_error")


# 关闭共享客户端:应用关闭钩子调用,释放连接池;幂等,未初始化时直接返回
async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
