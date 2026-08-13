"""知识库管理接口(仅 admin):上传 / 列表 / 详情 / 删除 / chunk 预览 / 统计。"""
import asyncio
import logging

from fastapi import APIRouter, File, Query, UploadFile

from app.core.deps import AdminUser, DbDep
from app.models import Document
from app.schemas.document import (
    AdminStats,
    ChunkListOut,
    ChunkOut,
    DocumentListOut,
    DocumentOut,
)
from app.services import document_service, ingestion_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


# 注意:admin/stats 必须先于 {doc_id} 注册,避免被路径参数吞掉
@router.get("/admin/stats", response_model=AdminStats)
async def admin_stats(db: DbDep, _admin: AdminUser):
    return await document_service.admin_stats(db)


@router.get("", response_model=DocumentListOut)
async def list_documents(
    db: DbDep,
    _admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
):
    items, total = await document_service.list_documents(db, page, page_size, keyword)
    return DocumentListOut(items=items, total=total, page=page, page_size=page_size)


@router.post("/upload")
async def upload_documents(
    db: DbDep,
    admin: AdminUser,
    files: list[UploadFile] = File(...),
):
    """批量上传并启动入库任务;立即返回文档列表,进度通过 GET /documents 轮询。"""
    created: list[Document] = []
    for f in files:
        doc = await document_service.save_upload(f)
        doc.uploaded_by = admin.id
        db.add(doc)
        await db.flush()
        created.append(doc)
    await db.commit()
    # schedule_ingestion 内部已 create_task,此处直接调度
    for doc in created:
        ingestion_service.schedule_ingestion(doc.id)
    return {"uploaded": len(created), "documents": [DocumentOut.model_validate(d) for d in created]}


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, db: DbDep, _admin: AdminUser):
    return await document_service.get_document(db, doc_id)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, db: DbDep, _admin: AdminUser):
    doc = await document_service.get_document(db, doc_id)
    await document_service.delete_document(db, doc)
    return {"ok": True}


@router.get("/{doc_id}/chunks", response_model=ChunkListOut)
async def list_chunks(
    doc_id: str,
    db: DbDep,
    _admin: AdminUser,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    items, total = await document_service.list_chunks(db, doc_id, page, page_size)
    return ChunkListOut(items=items, total=total, page=page, page_size=page_size)
