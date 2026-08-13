# 消息模型:会话内一问一答;assistant 消息附带检索引用来源,供前端展示"答案出自哪里"
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# conversation_id 外键归属会话;删会话时级联删除由服务层处理
class Message(Base):
    __tablename__ = "messages"
    # 复合索引(conversation_id, created_at):历史消息按时间倒序分页,索引支撑高效翻页
    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("conversations.id"), nullable=False)
    # role 决定消息方向(user/assistant),system 提示词在 RAG 流程中动态拼接,不入库
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | assistant
    # Text 类型不限长度:答案可能很长(如文档综述),避免截断
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 引用来源:[{index, doc_id, doc_title, page, section, snippet, score}]
    # 存文档标题快照:即使文档后续被删,历史答案的来源仍可展示
    sources: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # 消息状态:completed | error(流式中断时保留已生成部分)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="completed")
    feedback: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)  # 1 好 / -1 差
    # 反馈文本与分值并存:为后续用真实数据微调/评估回答质量提供标注
    feedback_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # token_count 记录本次回答的消耗,用于成本统计与上下文预算校准
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
