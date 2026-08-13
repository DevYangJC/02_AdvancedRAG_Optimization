# 会话模型:用户与助手的一次连续问答;一个会话挂多条消息(见 Message)
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# user_id 外键关联用户:会话严格归属本人,路由层据此做数据隔离
class Conversation(Base):
    __tablename__ = "conversations"
    # 复合索引(user_id, updated_at):列表按"最近更新"排序,该索引让排序走索引免全表扫描
    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)

    # 与 User 一致用 UUID 主键:跨表外键统一同类型同格式
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False)
    # 默认"新对话",用户可改;也可按首条消息自动生成标题(见 conversation_service)
    title: Mapped[str] = mapped_column(String(100), nullable=False, default="新对话")
    # created_at 记建会话时间;updated_at 随消息更新自动刷新,用于列表按活跃度排序
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
