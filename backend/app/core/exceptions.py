"""业务异常与统一错误体。

错误响应统一为:{"code": str, "message": str, "detail": dict|str|null}
code 为机器可读的错误码,message 为用户可读信息,detail 为可选的附加信息。
"""
# 错误码(code)供前端做程序化判断(如跳登录页),message 直接展示给用户;两者职责分离
# 所有业务异常统一继承 AppError:全局异常处理器据此返回 JSON,避免错误处理散落在各路由


class AppError(Exception):
    """业务异常基类。"""

    # 类属性即默认值:子类只需覆写 status_code 与 code,无需重复定义构造函数
    status_code = 500
    code = "INTERNAL_ERROR"

    # 保存原始 message/detail:上层异常处理器需要读取它们组装统一响应体
    def __init__(self, message: str, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = detail


# 400 参数错误:请求体非法或校验失败,前端应提示用户修正输入
class BadRequestError(AppError):
    status_code = 400
    code = "BAD_REQUEST"


# 401 未认证:token 缺失/过期/无效,前端应清除本地登录态并跳转登录页
class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


# 403 无权限:已登录但角色不允许(如普通用户访问管理接口)
class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


# 404 资源不存在:统一由业务层抛出,避免落到框架默认的纯文本 404
class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


# 409 冲突:唯一性约束被违反,如重复注册用户名;前端应展示"已存在"而非直接报错
class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


# 429 限流:触发速率限制,前端应提示"操作过于频繁"而非当作业务错误
class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


# 503 服务不可用:外部依赖(LLM/Qdrant)故障时抛出,让用户知道是服务问题而非请求问题
# 503 服务不可用:外部依赖(LLM/Qdrant)故障时抛出,让用户知道是服务问题而非请求问题
class ServiceUnavailableError(AppError):
    # 前端可据此提示"稍后重试",而不是反复提交请求
    status_code = 503
    code = "SERVICE_UNAVAILABLE"


# 统一响应体结构:前端用同一套解析逻辑处理所有错误,无需为每个接口单独写分支
def error_body(exc: AppError) -> dict:
    return {"code": exc.code, "message": exc.message, "detail": exc.detail}
