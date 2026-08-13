"""检索:查询向量化 → Qdrant dense top-K(支持按文档过滤)。"""
import logging

from app.rag.embedder import embed_query
from app.services import vector_service

logger = logging.getLogger(__name__)


# 检索入口:query=用户问题、top_k=召回条数、doc_ids 可选(限定文档范围);返回 [{payload, score}]
async def retrieve(query: str, top_k: int, doc_ids: list[str] | None = None) -> list[dict]:
    """返回 [{payload, score}] 按相似度降序。"""
    # 先把问题向量化:与库内文档向量同空间,余弦相似度才有可比性
    query_vector = await embed_query(query)
    # 稠密向量检索(dense retrieval):语义匹配而非关键词匹配,能召回"同义不同词"的段落
    hits = await vector_service.search(query_vector, top_k=top_k, doc_ids=doc_ids)
    # 日志截断到 30 字符:完整问题可能很长,日志只留辨识片段
    logger.info("检索完成: query=%s hits=%d", query[:30], len(hits))
    return hits
