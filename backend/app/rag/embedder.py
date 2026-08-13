"""Embedding 封装:通义 text-embedding-v3(云端 API)。

- OpenAIEmbeddings 指向 DashScope 兼容端点,1024 维
- CacheBackedEmbeddings + 磁盘 LocalFileStore:重复入库/重启不重复调用付费 API
- 批量 32 个一组提交
"""
# Embedding(向量化):把文本转为 1024 维向量,语义相近的文本向量距离也近,检索才有可比性
# 为什么套磁盘缓存:embedding 按 token 计费,重复入库/重启后重算等于白花钱
import asyncio
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# 通义 text-embedding 接口单次批量上限为 10,超出的请求会被拒绝
_embed_batch_size = 10
_cached_embedder = None


# 底层 embedder 包一层磁盘缓存(幂等单例,惰性创建:首次调用才初始化)
def get_cached_embedder():
    """底层 embedder 包一层磁盘缓存(幂等单例)。"""
    global _cached_embedder
    if _cached_embedder is None:
        from langchain.embeddings.cache import CacheBackedEmbeddings
        from langchain.storage import LocalFileStore
        from langchain_openai import OpenAIEmbeddings

        # 与 LLM 同一网关(DashScope 兼容端点),密钥配置共用
        raw = OpenAIEmbeddings(
            model=settings.embedding_model,
            base_url=settings.dashscope_base_url,
            api_key=settings.dashscope_api_key,
            # 维度显式指定:必须与 Qdrant 集合的 1024 维一致,否则检索直接报错
            dimensions=settings.embedding_dimensions,
            timeout=30,
            max_retries=2,
            # 不自动截断超长文本:长度由切分器保证,截断反而破坏语义
            check_embedding_ctx_length=False,
        )
        # CacheBackedEmbeddings 原理:先查缓存,未命中才调底层付费 API
        # LocalFileStore 落磁盘(data/models 下):缓存跨进程共享,重启不丢
        _cached_embedder = CacheBackedEmbeddings.from_bytes_store(
            raw,
            LocalFileStore("./data/models/embed_cache"),
            # namespace 按模型名隔离:换模型后旧缓存自动失效,不会串数据
            namespace=settings.embedding_model.replace("/", "__"),
        )
        logger.info("Embedding 已初始化: %s(%d 维, 磁盘缓存已启用)", settings.embedding_model, settings.embedding_dimensions)
    return _cached_embedder


# 批量向量化:参数 texts=文本列表,返回与输入顺序一一对应的向量列表
async def embed_documents(texts: list[str]) -> list[list[float]]:
    # 空列表短路:不发起任何 API 调用
    if not texts:
        return []
    # to_thread:embedder 是同步 SDK,放线程池避免阻塞事件循环
    embedder = await asyncio.to_thread(get_cached_embedder)
    vectors: list[list[float]] = []
    # 分批提交:每批不超过接口批量上限;缓存命中的批次几乎零延迟
    for i in range(0, len(texts), _embed_batch_size):
        batch = texts[i : i + _embed_batch_size]
        # extend 按批累积,顺序与输入保持一致
        vectors.extend(await asyncio.to_thread(embedder.embed_documents, batch))
    return vectors


# 单个查询向量(检索用):走独立入口,不走批量路径
async def embed_query(text: str) -> list[float]:
    embedder = await asyncio.to_thread(get_cached_embedder)
    # 与 embed_documents 使用同一模型,查询与库内向量同空间,相似度计算才有意义
    return await asyncio.to_thread(embedder.embed_query, text)
