"""RAG 评估任务与评估明细 ORM 模型。

EvalTask: 一次完整的评估任务(含进度、状态、汇总得分)
EvalRecord: 任务中每道题的评估明细(问题、回答、四维得分)
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class EvalTask(Base):
    """评估任务表：记录每次评估的整体状态、进度和汇总得分。"""
    __tablename__ = "eval_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # pending → generating → evaluating → done / failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # 0-100 整数进度
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 当前步骤描述(前端进度条下方提示文字)
    current_step: Mapped[str] = mapped_column(String(200), nullable=False, default="等待开始")
    # 四维汇总平均分(评估完成后写入)
    avg_faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_context_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_context_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 参与评估的源文档列表(JSON 字符串: ["商品说明.md", "商品参数.txt"])
    source_files: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 失败原因
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 关联明细记录
    records: Mapped[list["EvalRecord"]] = relationship("EvalRecord", back_populates="task", cascade="all, delete-orphan")


class EvalRecord(Base):
    """评估明细表：每道测试题的问题、回答、检索上下文和四维得分。"""
    __tablename__ = "eval_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("eval_tasks.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    ground_truth: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON 字符串: ["检索片段1", "检索片段2", ...]
    retrieved_contexts: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # 四维单题得分
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped["EvalTask"] = relationship("EvalTask", back_populates="records")
