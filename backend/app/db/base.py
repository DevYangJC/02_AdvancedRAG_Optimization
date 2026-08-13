"""ORM 声明基类与元数据。"""
from sqlalchemy.orm import DeclarativeBase


# 所有 ORM 模型的公共基类:继承它才被 SQLAlchemy 注册进 metadata,create_all 才能建出对应表
class Base(DeclarativeBase):
    # 无需额外行为:类体保留占位,所有表结构由各模型的字段声明决定
    pass
