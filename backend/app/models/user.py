# 用户模型:登录身份与权限的载体;密码只存哈希不存明文(哈希算法见 core/security.py)
import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# ORM 模型类:一张表一个类,字段声明即表结构,由 db/base.py 的 Base 注册进 metadata
class User(Base):
    __tablename__ = "users"

    # 主键用 UUID 字符串而非自增整数:对外接口不暴露自增序号,防止被遍历爬取
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 用户名唯一且建索引:登录按用户名精确匹配,索引保证查询不慢
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # 128 位长度容纳 bcrypt 输出;绝不把明文密码落库
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    # 角色决定权限:admin 可管理知识库/用户,user 仅普通问答;权限校验见 core/deps.py
    role: Mapped[str] = mapped_column(String(10), nullable=False, default="user")  # admin | user
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # server_default 由数据库写时间,避免应用层时钟不一致;updated_at 在 UPDATE 时自动刷新
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
