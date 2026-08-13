"""知识库文档相关请求/响应模型。"""
# 管理端界面渲染的数据形状与这些出参完全对齐,前后端以此为准联调
from datetime import datetime

from pydantic import BaseModel


# 文档出参:状态与切分进度直接返回,前端轮询时无需再请求详情接口
class DocumentOut(BaseModel):
    id: str
    # 展示用原始文件名(与存储文件名不同,见 models/document.py)
    filename: str
    # 类型决定前端图标与解析器
    file_type: str
    # 字节数,前端格式化显示为 "1.2 MB"
    size_bytes: int | None
    # processing/ready/failed/deleting 原样透出,前端按状态显示不同 UI
    status: str
    # 进度字段用于进度条:failed 时停在失败前的值,error 给出失败原因
    chunk_total: int
    chunk_processed: int
    # 解析失败原因(文件损坏/格式不支持),前端展示并允许重新处理
    error: str | None
    created_at: datetime

    # ORM 直转:document_service 返回的对象无需手动构造
    model_config = {"from_attributes": True}


# 文档列表分页结构,与其它列表接口保持一致,前端组件可复用
class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


# 切块出参:预览切分效果时逐块返回内容与来源信息
class ChunkOut(BaseModel):
    id: str
    # 块序号:前端按此还原文档阅读顺序
    chunk_index: int
    content: str
    # 页码/章节:展示引用位置,无则 None
    page: int | None
    section: str | None
    token_count: int | None

    model_config = {"from_attributes": True}


# 切块分页列表:文档详情页按页加载,避免一次返回上千条切块
class ChunkListOut(BaseModel):
    items: list[ChunkOut]
    total: int
    page: int
    page_size: int


# 管理端统计大盘:一次返回全部指标,仪表盘单请求渲染
class AdminStats(BaseModel):
    document_count: int
    chunk_count: int
    # 向量库条目数:与 chunk_count 对比可发现"向量未同步"的异常
    vector_count: int
    total_question_count: int
    cache_hit_count: int
    # 缓存命中率 = 命中数 / 总问题数:衡量语义缓存收益的核心指标
    cache_hit_rate: float
    user_count: int
    conversation_count: int
