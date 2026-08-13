"""文档入库后台任务(进程内 asyncio.Task)。

流程:加载 → 切分 → 写 chunks 表 → embedding(通义 API,批量)→ Qdrant 批量 upsert → 更新进度。
失败时置 status=failed 并记录 error;任务全程使用独立数据库会话,与请求会话隔离。
"""
# 为什么用进程内任务而非外部队列:入库链路不跨服务,进程内编排最简单可靠
# 失败兜底:异常统一在这里捕获并置 failed,绝不把底层异常抛回请求层
import asyncio
import logging

from sqlalchemy import select

from app.db.session import async_session_maker
from app.models import Chunk, Document
from app.rag.embedder import embed_documents
from app.rag.loaders import load_document
from app.rag.splitters import split_blocks
from app.services import vector_service

logger = logging.getLogger(__name__)

# 数据库与向量库的批量阈值分开控制:两者容量特性不同,互不牵连
# 64 是实测平衡点:过大单次事务内存高,过小网络/事务往返次数多
_UPSERT_BATCH = 64
_DB_BATCH = 64


# 粗略 token 估算(中文 1 字 ≈ 1 token,英文按 4 字符):入库时记录,供统计成本与限额
def _token_estimate(text: str) -> int:
    """粗略 token 估算(中文 1 字 ≈ 1 token,英文按 4 字符)。"""
    # 中英文混合文本:中文按字计,英文按 4 字符折算,估算量级足够用
    chinese = sum(1 for c in text if "一" <= c <= "鿿")
    return chinese + max(0, (len(text) - chinese) // 4)


# 入库任务入口:包裹 _ingest,任何异常都转为文档 failed 状态,保证前端可查询到失败原因
# 返回 None:调度层(ingestion_service)只关心任务是否结束,不关心返回值
async def run_ingestion(document_id: str) -> None:
    try:
        await _ingest(document_id)
    except Exception as e:  # noqa: BLE001
        logger.exception("文档入库失败: %s", document_id)
        # 独立会话写失败状态:不依赖请求会话,失败信息一定落库
        async with async_session_maker() as db:
            doc = await db.get(Document, document_id)
            if doc:
                doc.status = "failed"
                # 错误信息截断到 2000 字符:避免超长堆栈撑爆数据库字段
                doc.error = str(e)[:2000]
                await db.commit()


# 入库主流程五步:加载 → 切分 → 写库 → 向量化 → 回填,每一步都独立可重试
async def _ingest(document_id: str) -> None:
    async with async_session_maker() as db:
        doc = await db.get(Document, document_id)
        # deleting 状态跳过:删除中的文档不允许重新入库,避免删除/入库竞争
        if doc is None or doc.status == "deleting":
            return
        # 状态机:processing → ready/failed;deleting 是删除过渡态,不参与入库
        doc.status = "processing"
        doc.error = None  # 重试成功后清空旧错误信息,不再误导
        # 重置进度字段:重新入库时从 0 开始,前端进度条有准确分母
        doc.chunk_total = 0
        doc.chunk_processed = 0
        await db.commit()

        # 1. 加载与切分(IO/CPU 密集,线程池)
        # to_thread:解析/切分是同步重活,放线程池避免阻塞事件循环
        blocks = await asyncio.to_thread(load_document, doc.stored_path, doc.file_type)
        chunks = await asyncio.to_thread(split_blocks, blocks, doc.file_type == "md")
        # chunk_total 先落库:前端进度条据此渲染总进度
        doc.chunk_total = len(chunks)
        await db.commit()

        # 2. 批量写 chunks 表
        pending: list[Chunk] = []
        for c in chunks:
            pending.append(
                Chunk(
                    document_id=doc.id,
                    chunk_index=c.index,
                    content=c.content,
                    page=c.page,
                    section=c.section,
                    # token_count 供管理统计与成本估算使用
                    token_count=_token_estimate(c.content),
                )
            )
            # 分批 flush 而非一次 add_all:上万 chunk 时单次事务内存/锁压力过大
            if len(pending) >= _DB_BATCH:
                db.add_all(pending)
                await db.flush()
                pending.clear()
        if pending:
            # 尾部不足一批的剩余数据也要入库
            db.add_all(pending)
        # 分步 commit 的代价:中途崩溃时已提交的 chunk 保留,重跑可复用,不必全量重来
        await db.commit()

        # 3. 读取完整 chunk 列表,embedding 并批量写入 Qdrant
        # 重读而非复用 pending:向量化与向量写入需要与数据库记录顺序严格一致
        rows = (
            (await db.execute(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index)))
            .scalars()
            .all()
        )
        # embedding 是网络 IO:已由 embed_documents 内部分批与限流,这里只需传全量
        vectors = await embed_documents([r.content for r in rows])
        payloads = [
            {
                "doc_id": doc.id,
                "doc_title": doc.filename,
                "chunk_index": r.chunk_index,
                "page": r.page,
                "section": r.section,
                # chunk_content 冗余进 payload:检索命中时直接取原文展示,免一次数据库查询
                "chunk_content": r.content,
            }
            for r in rows
        ]
        # 批量 64 一组写入:匹配 Qdrant 单请求体积上限
        point_ids = await vector_service.upsert_batch(vectors, payloads, batch_size=_UPSERT_BATCH)

        # 4. 回填 qdrant_point_id 并置 ready
        # 回填 point_id:支撑后续按点删除与完整性校验
        for r, pid in zip(rows, point_ids):
            r.qdrant_point_id = pid
        # embedding 全部成功才置 ready:半截向量不可对外检索,避免命中残缺内容
        doc.status = "ready"
        doc.chunk_processed = len(rows)
        await db.commit()
        # 任务完成日志:文件名与 chunk 数,便于核对入库结果
        logger.info("文档入库完成: %s(%d chunks)", doc.filename, len(rows))
