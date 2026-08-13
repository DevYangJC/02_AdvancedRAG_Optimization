"""知识库文档服务:上传落盘、列表、删除级联、chunk 预览、统计。"""
# 文档是知识库的原子单位:上传后经入库任务切分、向量化,检索才能命中
# 文件落磁盘(uploads 目录),数据库只存元数据与路径——大文件不进数据库
# 注意:上传只落盘、不解析——解析/切分/向量化全部在入库后台任务中完成
import logging
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError
from app.models import Chunk, Conversation, Document, Message, User
from app.services import vector_service

logger = logging.getLogger(__name__)


# 扩展名白名单校验:未列出的类型一律拒绝,防止上传无法解析的文件
def _safe_ext(filename: str) -> str:
    # 扩展名小写归一:Windows 上传的 .PDF 与 .pdf 视为同一类型
    # 无扩展名(如 "README")一律拒绝:无法判定类型就选不出对应的加载器
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    # 白名单来自配置(allowed_extensions),新增格式无需改代码
    allowed = {e.strip() for e in settings.allowed_extensions.split(",")}
    if ext not in allowed:
        # 错误信息带上白名单:前端可直接提示用户支持哪些格式
        raise BadRequestError(f"不支持的文件类型 .{ext},允许: {', '.join(sorted(allowed))}")
    return ext


# 上传落盘:校验通过后写入 uploads 目录,返回待入库的 Document 记录(落库由调用方负责)
async def save_upload(upload: UploadFile) -> Document:
    """校验扩展名/大小,写入 uploads 目录(uuid 命名防路径注入),返回待入库记录。"""
    ext = _safe_ext(upload.filename or "file")
    # 先整体读入内存再判断大小:FastAPI 已限制请求体,这里是二次防御
    data = await upload.read()
    if len(data) > settings.upload_max_size_mb * 1024 * 1024:
        raise BadRequestError(f"文件超过大小限制 {settings.upload_max_size_mb}MB")
    # 空文件拒绝:0 字节切不出任何 chunk,入库没有意义
    if not data:
        raise BadRequestError("空文件")

    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    # 用 uuid 重命名而非原始文件名:原始名可能含路径分隔符/特殊字符,直接落盘有路径注入风险
    # uuid 名互不冲突:同一文件重复上传各自独立入库,互不覆盖
    stored_name = f"{uuid.uuid4()}.{ext}"
    stored_path = str(Path(settings.upload_dir) / stored_name)
    # write_bytes 一次写入,比流式拷贝简单可靠
    Path(stored_path).write_bytes(data)

    # filename 保留用户原始名(仅展示用),stored_path 才是服务端实际路径
    return Document(
        filename=upload.filename or stored_name,
        stored_path=stored_path,
        file_type=ext,
        size_bytes=len(data),
        status="processing",  # 初始状态:入库任务完成后置 ready/failed,前端据此展示进度
    )
    # 返回未落库的记录:由 API 层 db.add + commit,保证与其它业务同处一个事务


async def list_documents(
    db: AsyncSession, page: int, page_size: int, keyword: str | None = None
) -> tuple[list[Document], int]:
    # keyword 用 LIKE %kw% 两侧模糊:文件名任意位置命中即匹配;为空则跳过过滤
    # 参数: page/page_size 分页、keyword 可选关键字;返回 (当前页列表, 总数)
    stmt = select(Document).order_by(Document.created_at.desc())
    count_stmt = select(func.count()).select_from(Document)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(Document.filename.like(like))
        # 过滤同时作用于列表与总数:否则翻页时总数对不上
        count_stmt = count_stmt.where(Document.filename.like(like))
    total = (await db.execute(count_stmt)).scalar_one()
    # 按创建时间倒序:新上传的文档排在前面
    docs = (await db.execute(stmt.offset((page - 1) * page_size).limit(page_size))).scalars().all()
    # 返回 (当前页, 总数):总数供前端计算分页
    return list(docs), total


# 按 id 取文档,供删除/预览/统计等场景复用,避免各 API 重复查询逻辑
async def get_document(db: AsyncSession, doc_id: str) -> Document:
    doc = await db.get(Document, doc_id)
    if doc is None:
        raise NotFoundError("文档不存在")
    # 不做归属校验:文档属于全站知识库,任何登录用户可读
    return doc


# 级联删除:置 deleting → 删向量 → 删 chunks → 删文件 → 删记录,任一步失败不阻断后续
# 参数: doc 为已加载的 Document 对象(由调用方传参,避免函数内重复查询)
async def delete_document(db: AsyncSession, doc: Document) -> None:
    """级联删除:置 deleting → 删 Qdrant 向量 → 删 chunks → 删文件 → 删记录。"""
    # 先置 deleting 并提交:前端与入库任务据此得知删除中,避免并发操作
    doc.status = "deleting"
    await db.commit()
    try:
        # 先删向量再删数据库记录:向量库是独立系统,其失败不应卡死整个删除流程
        await vector_service.delete_by_document(doc.id)
    except Exception as e:  # noqa: BLE001
        # 向量删除失败仅记日志:遗留向量成"孤儿点"可在运维侧清理,不让用户删除被阻塞
        logger.error("删除向量失败 doc=%s: %s", doc.id, e)
    await db.execute(Chunk.__table__.delete().where(Chunk.document_id == doc.id))
    # missing_ok=True:文件可能已被手动清理,删除时不再报错
    Path(doc.stored_path).unlink(missing_ok=True)
    # 文件删除在删记录之前完成:若中途失败可重试,不产生"记录没了文件还在"的孤儿
    await db.delete(doc)
    await db.commit()


# chunk 预览(文档详情页展示切分结果):分页防止大文档一次渲染过多
# 参数: doc_id=目标文档;文档存在性校验由 API 层完成,这里只负责数据
async def list_chunks(db: AsyncSession, doc_id: str, page: int, page_size: int) -> tuple[list[Chunk], int]:
    # total 与 rows 分开查询:total 供分页,rows 只取当前页
    total = (
        await db.execute(select(func.count()).select_from(Chunk).where(Chunk.document_id == doc_id))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Chunk)
            .where(Chunk.document_id == doc_id)
            # 按 chunk_index 升序:忠实呈现切分顺序,便于用户理解检索命中位置
            .order_by(Chunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total


# 管理后台统计:一次返回全站核心指标,各表独立 count,互不干扰
async def admin_stats(db: AsyncSession) -> dict:
    # 文档/块/用户/会话四表基数构成知识库规模概览
    doc_count = (await db.execute(select(func.count()).select_from(Document))).scalar_one()
    chunk_count = (await db.execute(select(func.count()).select_from(Chunk))).scalar_one()
    user_count = (await db.execute(select(func.count()).select_from(User))).scalar_one()
    conv_count = (await db.execute(select(func.count()).select_from(Conversation))).scalar_one()
    # question_count 只计用户消息:assistant 消息是回答而非提问
    question_count = (
        await db.execute(select(func.count()).select_from(Message).where(Message.role == "user"))
    ).scalar_one()
    cache_hits, cache_total = await _cache_stats(db)
    # 向量库是外部依赖:Qdrant 不可用时降级为 0,统计页不崩溃
    try:
        vector_count = (await vector_service.collection_stats()).get("points_count", 0)
    except Exception:  # noqa: BLE001
        vector_count = 0
    return {
        "document_count": doc_count,
        "chunk_count": chunk_count,
        "vector_count": vector_count,
        "total_question_count": question_count,
        "cache_hit_count": cache_hits,
        # 命中率四舍五入 4 位小数,前端直接展示百分比;无缓存时记 0 避免除零
        "cache_hit_rate": round(cache_hits / cache_total, 4) if cache_total else 0.0,
        "user_count": user_count,
        "conversation_count": conv_count,
    }
    # 返回结构对齐管理后台前端字段命名,新增指标时需同步前端


# 缓存统计:total = 条目数 + 历史命中次数;命中率口径与 admin_stats 展示一致
async def _cache_stats(db: AsyncSession) -> tuple[int, int]:
    from app.models import CacheEntry

    total = (await db.execute(select(func.count()).select_from(CacheEntry))).scalar_one()
    # 每条缓存记录的 hit_count 累加即历史命中数;coalesce 把空表的 NULL 归为 0
    hits = (await db.execute(select(func.coalesce(func.sum(CacheEntry.hit_count), 0)))).scalar_one()
    # 请求总数 ≈ 条目数 + 命中数:命中时记录还在,未命中才新建条目
    return hits, total + hits
