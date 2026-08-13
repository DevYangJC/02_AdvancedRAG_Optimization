# 切块模型:文档切分后的片段,与 Qdrant 中的向量点一一对应(业务库镜像)
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# 向量只存 Qdrant,业务库存一份纯文本镜像:切分预览、删除校验、审计都走这里
class Chunk(Base):
    """向量在业务库的镜像:用于切分预览、审计、删除校验。"""

    __tablename__ = "chunks"
    # 复合索引(document_id, chunk_index):同一文档的块序号连续有序,前端按此还原阅读顺序
    __table_args__ = (Index("ix_chunks_document_index", "document_id", "chunk_index"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # 外键指向文档;删除文档时需先删这里再删向量,顺序由服务层控制
    document_id: Mapped[str] = mapped_column(String(36), ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    # 切块原文:检索命中后直接返回给前端展示;Text 类型容纳长段落
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 页码与章节标题(若有):展示"引用自第几页/哪一节",提升答案可信度
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 估算上下文占用与成本;也可在召回时做 token 预算过滤
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 与向量库中的 point id 对齐:重建索引/删除时双向同步都靠它
    qdrant_point_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 切分入库时间:定位"何时进入向量库",排查向量未更新问题时有用
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
