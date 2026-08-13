# 语义缓存表:完全相同的问题直接复用上次答案,省一次 LLM 调用与费用
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# 缓存命中要求问题规范化后一致(如去除标点/空格差异),比向量检索更严格也更快
class CacheEntry(Base):
    """语义缓存:规范化问题 → 答案 + 引用来源。"""

    __tablename__ = "cache_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # md5(query) 做唯一键:比直接存长文本作索引更省空间;查询时先算哈希再精确匹配
    query_hash: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)  # md5
    # 原文与答案都留存:清缓存/审计时能追溯"什么问题、当时答了什么"
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    # 命中时返回的引用来源与首次回答一致,保证同一问题答案和出处都稳定
    sources: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # 记录生成时用的模型:模型升级后旧缓存按需作废,避免新旧模型答案混用
    model: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    # 命中次数统计:管理端展示缓存命中率,判断缓存是否值得保留
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # TTL 过期条目由后台任务定期清理(见 main.py 的 _cache_cleanup_loop)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
