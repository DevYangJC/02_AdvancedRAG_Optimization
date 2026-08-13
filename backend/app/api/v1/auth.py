"""认证接口:注册 / 登录 / 刷新 / 当前用户 / 修改密码。"""
# 认证路由全部公开(不要求登录),限流是这里唯一的防护手段
from fastapi import APIRouter, Request

from app.core.deps import CurrentUser, DbDep
from app.core.limiter import limiter
from app.core.security import decode_token
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserOut,
)
from app.services import auth_service

# 统一 /auth 前缀与标签:OpenAPI 文档按组展示;子路由由 v1/router.py 汇总挂载
router = APIRouter(prefix="/auth", tags=["auth"])


# 注册即登录:注册成功后直接发 token,省去"注册完再跳登录页"的步骤
# response_model=TokenResponse:FastAPI 按此模型校验并序列化返回值,字段错误在开发期即暴露
@router.post("/register", response_model=TokenResponse)
# 注册接口按 IP 限 10 次/分钟:防撞库、防批量刷号
@limiter.limit("10/minute")
async def register(request: Request, body: RegisterRequest, db: DbDep):
    # body 由 RegisterRequest 自动校验(用户名/密码规则见 schemas/auth.py)
    user = await auth_service.register(db, body.username, body.password, body.nickname)
    access, refresh = auth_service.issue_tokens(user)
    # 与登录/刷新共用同一响应结构:前端三个入口一套解析逻辑
    return TokenResponse(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


# 登录:校验用户名密码,成功发双 token;失败抛 401 由全局处理器返回统一错误体
@router.post("/login", response_model=TokenResponse)
# 登录同样限流:暴力破解字典攻击主要打这个端点
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: DbDep):
    # authenticate 返回用户或抛异常;密码明文只在内存中短暂存在
    user = await auth_service.authenticate(db, body.username, body.password)
    access, refresh = auth_service.issue_tokens(user)
    return TokenResponse(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


# 刷新令牌:access 过期后用 refresh 换新,实现"无感续期";只认 type=refresh 的令牌
@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: DbDep):
    user_id = decode_token(body.refresh_token, "refresh")
    # 回查数据库:refresh 有效但用户可能已被删除,这里统一拦截
    user = await auth_service.refresh_user(db, user_id)
    access, refresh = auth_service.issue_tokens(user)
    return TokenResponse(access_token=access, refresh_token=refresh, user=UserOut.model_validate(user))


# 当前用户信息:前端刷新页面后用它恢复登录态;依赖层已完成 token 校验
@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser):
    return current_user


# 修改密码:登录态(CurrentUser)+ 旧密码双重校验;改完不强制重登,由前端自行处理
@router.put("/password")
async def change_password(body: PasswordChangeRequest, db: DbDep, current_user: CurrentUser):
    await auth_service.change_password(db, current_user, body.old_password, body.new_password)
    return {"ok": True}
