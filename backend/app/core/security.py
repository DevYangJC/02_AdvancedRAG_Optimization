"""密码哈希(bcrypt)与 JWT 双 token 签发/校验。"""
# bcrypt:加盐哈希算法,即使数据库泄露,彩虹表/暴力破解也难以还原明文密码
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings
from app.core.exceptions import UnauthorizedError


# ---------- 密码 ----------
# 密码绝不存明文,只存 bcrypt 哈希;验证时做恒定时比较,防时序侧信道

# gensalt() 每次生成随机盐:同一密码每次哈希结果不同,撞库无法批量破解
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# 返回布尔而非抛异常:登录失败统一提示"用户名或密码错误",不暴露是哪一步失败
def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # 哈希格式非法(如旧数据迁移脏数据)时 checkpw 抛 ValueError,按"不匹配"处理
        return False


# ---------- JWT ----------
# JWT(JSON Web Token):服务端签名的无状态凭证;双 token 机制 = access 短效(2h)随请求携带
# + refresh 长效(14 天)仅用于换新,被盗后的可利用窗口被大幅压缩

# access/refresh 共用签发逻辑,只差 type 与有效期,抽出避免重复代码
def _create_token(subject: str, token_type: str, expire_delta: timedelta) -> str:
    # iat/exp 统一用 UTC:避免服务器时区差异导致令牌提前过期或"看起来未过期"
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expire_delta,
    }
    # 载荷只放 sub/type 等必要信息:JWT 载荷只是 base64 编码,放敏感数据等于公开
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


# 访问令牌:每次请求携带,过期后由客户端用刷新令牌换新,无需重新输入密码
def create_access_token(user_id: str) -> str:
    return _create_token(user_id, "access", timedelta(minutes=settings.jwt_access_expire_minutes))


# 刷新令牌:仅在 /auth/refresh 使用,泄露面比 access 小;生产环境可再加轮换与吊销机制
def create_refresh_token(user_id: str) -> str:
    return _create_token(user_id, "refresh", timedelta(days=settings.jwt_refresh_expire_days))


# 统一验签入口:所有解析失败都转成业务异常,路由层无需处理 jwt 库的具体异常类型
# 校验只依赖签名与声明的密钥,不查询数据库,因此 O(1) 且天然无状态
def decode_token(token: str, expected_type: str = "access") -> str:
    """校验并解析 token,返回 user_id;失败统一抛 401。"""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        # 过期是最常见的失败原因,单独给出友好提示,前端据此引导重新登录
        raise UnauthorizedError("登录已过期,请重新登录", "token_expired")
    except jwt.InvalidTokenError:
        raise UnauthorizedError("无效的登录凭证", "token_invalid")
    # 防混淆:refresh 令牌不能当 access 用(反之亦然),双重校验降低重放风险
    if payload.get("type") != expected_type:
        raise UnauthorizedError("无效的登录凭证", "token_type_mismatch")
    # sub 缺失的令牌视为无效,避免后续拿到 None 去查库
    subject = payload.get("sub")
    if not subject:
        raise UnauthorizedError("无效的登录凭证", "token_no_subject")
    return subject
