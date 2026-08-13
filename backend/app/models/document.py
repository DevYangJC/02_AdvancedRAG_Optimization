# 文档模型:知识库的基本单元;上传→切分→向量化的进度与结果都记录在本表
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


# 文档与切块(Chunk)是 1:N:一个文档切出多个片段进向量库,此处只存文件级元数据
class Document(Base):
    __tablename__ = "documents"

    # UUID 主键同时作为磁盘文件名:防猜测真实文件名,也规避中文名路径问题
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # 原始文件名
    # 存重命名后的服务器路径:原始文件名与存储名分离,同名文件互不覆盖
    stored_path: Mapped[str] = mapped_column(String(500), nullable=False)  # data/uploads/{uuid}.{ext}
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf/docx/xlsx/txt/md
    # 文件类型决定用哪个解析器;只允许配置文件声明的类型,防恶意格式
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # processing | ready | failed | deleting(failed 时 error 字段给出原因,前端可重新处理)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="processing")
    # 进度对:大文件切分耗时,前端轮询这两个字段显示进度条
    chunk_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 解析/切分失败原因(文件损坏、格式不支持等),随状态返回给前端
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 记录上传人:管理端可按人统计/追溯;NULL 表示系统或历史数据导入
    uploaded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    # created_at 记录上传时间;updated_at 在切分完成/状态变更时刷新,供"最近更新"排序
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
