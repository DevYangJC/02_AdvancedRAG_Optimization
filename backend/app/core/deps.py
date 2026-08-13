"""FastAPI 依赖注入:数据库会话、当前用户、管理员校验。"""
# 依赖注入(DI):把"怎么拿数据库连接、怎么校验身份"从业务路由中抽离,统一在这里完成
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.db.session import async_session_maker
from app.models import User


# 请求级数据库会话:FastAPI 在请求处理完自动关闭,yield 模式保证连接不泄漏
async def get_db() -> AsyncSession:
    async with async_session_maker() as session:
        yield session


# Annotated + Depends 是 FastAPI 官方推荐的依赖声明写法:路由函数只需写 db: DbDep
DbDep = Annotated[AsyncSession, Depends(get_db)]


# Bearer 认证:HTTP 标准的无状态令牌认证方式,请求头形如 "Authorization: Bearer <token>"
# 从请求头解析出 token;缺失或格式错误一律视为未登录
def _extract_bearer_token(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    # 用 startswith 而非先截取再判断,畸形请求头不会被误解析
    if not auth.startswith("Bearer "):
        raise UnauthorizedError("未登录,请先登录", "missing_token")
    return auth[7:].strip()


# 解析 token 得到 user_id 后必须回查数据库:token 只能证明"登录过",不能证明"用户仍存在"
async def get_current_user(request: Request, db: DbDep) -> User:
    token = _extract_bearer_token(request)
    user_id = decode_token(token, "access")
    user = await db.get(User, user_id)
    # 用户可能已被管理员删除但 token 未过期,这里统一拦截并给出"未登录"提示
    if user is None:
        raise UnauthorizedError("用户不存在", "user_not_found")
    return user


# 路由参数写 user: CurrentUser 即自动完成身份校验,无需在函数体内重复解析 token
CurrentUser = Annotated[User, Depends(get_current_user)]


# 角色校验放在依赖层:所有管理接口复用同一逻辑,不散落在各路由函数里
async def require_admin(current_user: CurrentUser) -> User:
    if current_user.role != "admin":
        raise ForbiddenError("仅管理员可执行此操作")
    return current_user


# 管理接口声明 admin: AdminUser,未授权请求在进入函数体之前就被拦截
AdminUser = Annotated[User, Depends(require_admin)]
