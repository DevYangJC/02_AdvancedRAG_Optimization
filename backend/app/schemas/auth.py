"""认证相关请求/响应模型。"""
# Pydantic 模型即"请求/响应契约":FastAPI 据此自动生成 OpenAPI 文档、校验入参、序列化出参
import re
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

# 直接 import 业务异常:校验失败抛出的就是前端统一的错误体,而非 Pydantic 默认的 422 格式
from app.core.exceptions import BadRequestError

# 用户名规则集中定义:字母/数字/下划线/中文 2-50 位;正则与数据库校验双保险
USERNAME_PATTERN = r"^[a-zA-Z0-9_一-鿿]{2,50}$"


# 密码校验在注册/改密两处复用,抽出为独立函数避免重复
def validate_password(v: str) -> str:
    # 短密码最易被爆破,6 位是最低门槛
    if len(v) < 6:
        raise BadRequestError("密码至少 6 位")
    # 64 上限防止超长密码拖慢 bcrypt 哈希计算
    if len(v) > 64:
        raise BadRequestError("密码最长 64 位")
    return v


# 注册请求:用户名/密码必填,昵称选填;校验器在字段解析时自动触发
class RegisterRequest(BaseModel):
    username: str = Field(min_length=2, max_length=50)
    password: str
    # 昵称可为空:界面回退显示用户名
    nickname: str | None = Field(default=None, max_length=50)

    # field_validator 在字段进入模型前执行,失败即抛 400
    @field_validator("username")
    @classmethod
    def _check_username(cls, v: str) -> str:
        # 正则锚定 ^...$ 必须全串匹配,防止 "abc!admin" 这类中间注入
        if not re.match(USERNAME_PATTERN, v):
            raise BadRequestError("用户名需为 2-50 位字母、数字、下划线或中文")
        return v

    # 复用统一密码规则,保持注册与改密口径一致
    @field_validator("password")
    @classmethod
    def _check_password(cls, v: str) -> str:
        return validate_password(v)


# 登录请求:明文密码只在此处短暂存在,验证后即丢弃,不落任何日志
class LoginRequest(BaseModel):
    username: str
    password: str


# 刷新令牌请求:access 过期后用 refresh 换新,见 /auth/refresh 接口
class RefreshRequest(BaseModel):
    refresh_token: str


# 修改密码:必须带旧密码校验身份,防止 token 泄露后被恶意改密
class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

    # 新密码同样走 6-64 规则;是否与旧密码相同交给用户自行决定
    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, v: str) -> str:
        return validate_password(v)


# 用户出参:只暴露非敏感字段,password_hash 绝不外泄;role 一并返回供前端显示管理入口
class UserOut(BaseModel):
    id: str
    username: str
    nickname: str | None
    role: str
    created_at: datetime

    # 开启后 FastAPI 可直接返回 ORM 对象,自动映射同名属性
    model_config = {"from_attributes": True}


# 登录/注册/刷新统一返回该结构:前端一次拿到 access + refresh + 用户信息
class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    # token_type=bearer 是 OAuth2 约定字段:前端按此拼接 Authorization 头
    token_type: str = "bearer"
    user: UserOut
