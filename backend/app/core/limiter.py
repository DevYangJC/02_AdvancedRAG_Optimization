"""全局限流器单例(slowapi)。

- 装饰器与 app.state.limiter 必须用同一实例,enabled 开关才能全局生效
- 具体限流规则在各路由上通过 @limiter.limit(...) 声明
"""
# slowapi:为 FastAPI 提供按路由声明的限流能力,实现基于 flask-limiter
from slowapi import Limiter
from slowapi.util import get_remote_address

# 按客户端 IP 限流:未登录请求没有更好的身份依据,IP 是唯一可用的键
# 全局默认 120 次/分钟兜底,更细的规则在各路由用 @limiter.limit(...) 覆盖
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])
