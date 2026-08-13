"""认证业务:注册、登录、改密。"""
# 安全基线:密码只存"哈希+盐"后的单向结果,数据库泄露也无法反推出明文
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError, UnauthorizedError
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.models import User


# 注册新用户:参数 db=数据库会话、username/password 必填、nickname 缺省时取用户名;
# 返回已落库的 User;用户名冲突抛 BadRequestError(由全局异常处理器转 400)。
async def register(db: AsyncSession, username: str, password: str, nickname: str | None = None) -> User:
    # 先查重再插入:返回友好的"用户名已存在"提示,而非撞数据库唯一约束的底层报错
    existing = await db.scalar(select(User).where(User.username == username))
    if existing:
        raise BadRequestError("用户名已存在")
    # bcrypt 是 CPU 密集同步调用(约 100-300ms):放线程池,避免阻塞事件循环导致并发登录串行化
    password_hash = await asyncio.to_thread(hash_password, password)
    user = User(username=username, password_hash=password_hash, nickname=nickname or username)
    db.add(user)
    # commit 后 refresh:回读数据库生成的 id/created_at,保证返回对象字段完整
    await db.commit()
    await db.refresh(user)
    return user


# 登录校验:用户名与密码哈希一次查询比对完成,返回 User 供签发令牌
async def authenticate(db: AsyncSession, username: str, password: str) -> User:
    # 用户不存在与密码错误返回同一提示与错误码:防止攻击者批量探测已注册用户名
    user = await db.scalar(select(User).where(User.username == username))
    # verify_password 同样走线程池:同步校验 100-300ms,阻塞事件循环会拖垮并发登录
    ok = user is not None and await asyncio.to_thread(verify_password, password, user.password_hash)
    if not ok:
        raise UnauthorizedError("用户名或密码错误", "bad_credentials")
    return user


# 修改密码:先验证旧密码,防止他人借已登录会话直接改密
async def change_password(db: AsyncSession, user: User, old_password: str, new_password: str) -> None:
    if not await asyncio.to_thread(verify_password, old_password, user.password_hash):
        raise BadRequestError("原密码不正确")
    # 直接改内存对象的哈希并提交即可,无需重新查询
    user.password_hash = hash_password(new_password)
    await db.commit()


# 签发令牌对:access 短时效(约 30 分钟)用于常规鉴权,refresh 长时效(7 天)用于续签;
# 双令牌分离可缩小 access 泄露后的攻击窗口(泄露也只在短时间内有效)
def issue_tokens(user: User) -> tuple[str, str]:
    return create_access_token(user.id), create_refresh_token(user.id)


# 刷新令牌场景:按 id 重取用户,确认账号未被删除;已删账号的旧令牌立即失效
async def refresh_user(db: AsyncSession, user_id: str) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    return user
