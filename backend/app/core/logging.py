"""结构化日志:request_id 全链路关联 + 控制台/文件双输出。

- 每个请求分配 request_id(写入响应头 X-Request-Id),日志统一携带
- 格式:时间 | 级别 | request_id | 模块:行号 | 消息
"""
# request_id 是排查问题的抓手:前端报错时带回 X-Request-Id,后端按 id 即可串联整条请求的日志
import logging
import sys
import uuid
from contextvars import ContextVar
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

# ContextVar 是 asyncio 下的"请求级全局变量":同一请求内所有协程共享同一 request_id,互不串扰
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


# 业务代码取当前请求 id:拼进自己的日志或返回给前端,方便问题定位
def get_request_id() -> str:
    return _request_id.get()


# logging.Filter 在每条日志发出前执行:把 request_id 注入 LogRecord,格式化时即可引用 %(request_id)s
class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id.get()
        return True


# 幂等初始化:热重载/多模块重复调用时不会叠加出多份重复的日志输出
def setup_logging(log_dir: str = "data/logs") -> None:
    root = logging.getLogger()
    # uvicorn 已配置过根 logger 时直接跳过,避免控制台重复打印
    if root.handlers:
        return

    # 先建目录再挂文件 handler:否则首次启动会因目录不存在直接失败
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    # 固定格式便于脚本解析;request_id 列让运维能按一次请求切片分析
    fmt = "%(asctime)s | %(levelname)-7s | %(request_id)s | %(name)s:%(lineno)d | %(message)s"
    formatter = logging.Formatter(fmt)

    # 控制台输出走 stderr:与业务 stdout 输出分离,符合服务端日志惯例
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(_RequestIdFilter())
    root.addHandler(console)

    # 延迟导入:该模块在 logging 初始化早期可能不可用,函数内导入避免启动期报错
    from logging.handlers import TimedRotatingFileHandler

    # TimedRotatingFileHandler 是标准库的轮转实现,无需引入第三方依赖
    # 按天轮转日志文件并保留 14 天:避免单文件无限增长,便于按天归档与磁盘管理
    file_handler = TimedRotatingFileHandler(
        Path(log_dir) / "app.log",
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_RequestIdFilter())
    root.addHandler(file_handler)

    # 统一 INFO 级别:DEBUG 会输出 SQL 与敏感数据,生产环境不开
    root.setLevel(logging.INFO)
    # 双 handler 共用同一 formatter/filter:控制台与文件日志格式完全一致,对照排查无落差



# 中间件在路由执行之前拦截所有请求;若上游(如 Nginx)已传 X-Request-Id 则沿用,支持跨服务追踪
class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个 HTTP 请求分配 request_id 并写入响应头。"""

    # 只需覆写 dispatch:它对所有请求生效,无需逐路由注册
    async def dispatch(self, request: Request, call_next) -> Response:
        # 优先沿用调用方传入的 id;没有则生成 16 位十六进制,长度适中且碰撞概率可忽略
        rid = request.headers.get("X-Request-Id") or uuid.uuid4().hex[:16]
        # 设置后,本次请求内后续所有日志自动带上该 id
        _request_id.set(rid)
        try:
            response = await call_next(request)
        finally:
            # 无论成功或异常都要重置,防止上一个请求的 id 泄漏进下一个请求的日志
            _request_id.set("-")
        # 响应头回传 id:前端/运维凭它即可在日志中检索整条请求链路
        response.headers["X-Request-Id"] = rid
        return response

