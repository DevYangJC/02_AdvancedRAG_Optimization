"""Qdrant 向量库服务:客户端单例、collection 管理、写入/检索/级联删除。

- 集合 product_docs:1024 维 Cosine(text-embedding-v3)
- payload: {doc_id, doc_title, chunk_index, page, section, text_hash}
- 对 doc_id 建 keyword payload 索引,支撑按文档过滤与级联删除
- 本文件为向量库唯一抽象层:若需切换 Chroma 等,只改此文件
"""
# 全站只经此文件访问 Qdrant;换向量库(如 Chroma/Milvus)时只需改这一层
# 检索语义:1024 维余弦相似度——向量越接近,文本语义越相关
# payload 设计:doc_id/doc_title 支撑按文档过滤与引用展示;chunk_content 免回查数据库
import logging
import uuid

from qdrant_client import AsyncQdrantClient, models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: AsyncQdrantClient | None = None


# 获取全局客户端单例(惰性创建):AsyncQdrantClient 内部维护连接池,多请求共享复用
def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        import httpx

        # 关键:qdrant-client 对 localhost 默认 max_keepalive_connections=0(每次请求新建连接)。
        # 本机 TCP 建连有 200-500ms 环境开销(安全软件检查),每次检索都付建连成本会拖垮延迟;
        # 显式开启 keep-alive 连接复用,实测检索延迟 250ms → 2ms
        _client = AsyncQdrantClient(
            url=settings.qdrant_url,
            timeout=15,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=10),
        )
    # 注意:多进程部署下每进程持有独立客户端,连接数按进程累计
    return _client


# 关闭客户端:应用关闭钩子调用,释放连接池;幂等,未初始化时直接返回
async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None  # 置空后允许进程内重新创建


# 健康检查:启动时探测 Qdrant 是否可用,任何异常都视为不可用,不抛错打断启动
# 返回值: True=可达、False=不可达(供启动引导与健康检查使用)
async def ping_qdrant() -> bool:
    try:
        # 只做轻量查询(get_collections),不做任何写操作
        await get_client().get_collections()
        return True
    except Exception:  # noqa: BLE001
        # 不缓存探测结果:每次调用实时反映当前可用性
        return False


# 确保集合存在:不存在则创建,幂等;每次写前探测的成本远低于"集合缺失时批量失败"
async def ensure_collection() -> None:
    client = get_client()
    try:
        # 已存在则直接通过,不做任何事
        await client.get_collection(settings.qdrant_collection)
    except UnexpectedResponse:
        # Qdrant 对不存在的集合返回 UnexpectedResponse,以此为创建信号
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                # 维度与 text-embedding-v3 输出对齐;换 embedding 模型需重建集合
                size=settings.embedding_dimensions, distance=models.Distance.COSINE
            ),
        )
        # 对 doc_id 建 keyword 索引:按文档过滤/删除从全表扫描降为索引命中
        await client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="doc_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        # 创建日志便于排查"检索不到"之类的集合配置问题
        logger.info("已创建向量集合 %s(%d 维 Cosine)", settings.qdrant_collection, settings.embedding_dimensions)


async def upsert_batch(
    vectors: list[list[float]],
    payloads: list[dict],
    point_ids: list[str] | None = None,
    batch_size: int = 64,
) -> list[str]:
    """批量写入向量;返回 point_id 列表(与输入一一对应)。"""
    # 参数: vectors=向量列表、payloads=元数据列表(必须等长一一对应)、point_ids 可选指定
    # point_id 缺省用 uuid 生成:调用方无需自行管理 id,同名文档重传也不会冲突
    ids = point_ids or [str(uuid.uuid4()) for _ in range(len(vectors))]
    # batch_size 默认 64:在请求体积与往返次数之间取平衡
    client = get_client()
    # 分批是硬需求:Qdrant 单次 upsert 有请求体积上限,大文档必然要拆分
    # 已写入的批次不因后续批次失败而回滚(向量库写多读少,重跑任务幂等)
    for i in range(0, len(vectors), batch_size):
        await client.upsert(
            collection_name=settings.qdrant_collection,
            points=[
                models.PointStruct(id=ids[j], vector=vectors[j], payload=payloads[j])
                # min 防越界:最后一批往往不足 batch_size
                for j in range(i, min(i + batch_size, len(vectors)))
            ],
        )
    # 返回 ids 供调用方回填 qdrant_point_id,后续按点删除/校验时使用
    return ids


async def delete_by_document(doc_id: str) -> int:
    """按 doc_id payload 过滤删除该文档的全部向量,返回删除数量。"""
    # 参数: doc_id=目标文档 id;用于文档删除与重新入库前的向量清理
    # 用 FilterSelector 按 payload 过滤:只命中该文档的点,绝不误伤其它文档
    deleted = await get_client().delete(
        collection_name=settings.qdrant_collection,
        points_selector=models.FilterSelector(
            filter=models.Filter(
                must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
            )
        ),
    )
    # 幂等:文档无向量时返回 0,不会报错;数量供调用方判断清理是否生效
    # 该接口同时服务"删除文档"与"重新入库"两个场景,清理语义一致
    return deleted.deleted.count if deleted.deleted else 0


# 统计某文档的向量点数:入库进度与完整性校验使用
async def count_by_document(doc_id: str) -> int:
    # exact=True 精确计数:近似计数(默认 sketch)会带来进度误差
    result = await get_client().count(
        collection_name=settings.qdrant_collection,
        # 过滤结构与 search/delete 一致,语义统一
        count_filter=models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
        ),
        exact=True,
    )
    return result.count


async def search(
    query_vector: list[float],
    top_k: int,
    doc_ids: list[str] | None = None,
    score_threshold: float | None = None,
) -> list[dict]:
    """向量检索;返回 [{payload, score}]。"""
    # 参数: query_vector=查询向量、top_k=返回条数、doc_ids 可选(过滤范围)、score_threshold 可选
    query_filter = None
    if doc_ids:
        # 元素统一转 str:数据库 id 可能是整数型,防止类型不匹配导致过滤失效
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="doc_id",
                    match=models.MatchAny(any=[str(d) for d in doc_ids]),
                )
            ]
        )
    # qdrant-client 1.19+:search 已迁移为 query_points(query API)
    result = await get_client().query_points(
        collection_name=settings.qdrant_collection,
        query=query_vector,
        limit=top_k,
        query_filter=query_filter,
        # score_threshold 兜底:低于阈值的弱相关结果直接丢弃
        score_threshold=score_threshold,
        # payload 必须带回:引用展示(doc 标题/页码/原文)全靠它,回查数据库代价高
        with_payload=True,
    )
    # 统一成 {payload, score} 结构:调用方不接触 qdrant 原始点对象
    # score 即余弦相似度,范围 [-1,1],越大越相关,可直接用于排序与展示
    return [{"payload": h.payload, "score": h.score} for h in result.points]


# 集合统计:点数与状态,管理后台仪表盘展示;返回 {"points_count": 点数, "status": 状态字符串}
async def collection_stats() -> dict:
    info = await get_client().get_collection(settings.qdrant_collection)
    # points_count 新建集合时可能为 None,归 0 兜底;status 字符串化便于直接展示比较
    return {"points_count": info.points_count or 0, "status": str(info.status)}
