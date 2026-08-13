"""入库任务调度:启动 asyncio 任务并跟踪运行状态。"""
# 采用进程内 asyncio.Task 而非 Celery 等任务队列:单机入库量级小,无需额外中间件依赖
import asyncio
import logging

from app.tasks.ingestion import run_ingestion

logger = logging.getLogger(__name__)

# 运行中的任务:doc_id -> asyncio.Task;以文档为单位去重,重复上传请求只触发一次入库
_running: dict[str, asyncio.Task] = {}


# 启动/复用入库任务;参数 document_id=文档 id,返回 Task 供调用方跟踪状态
def schedule_ingestion(document_id: str) -> asyncio.Task:
    """启动/复用入库任务(同一文档只跑一个)。"""
    existing = _running.get(document_id)
    if existing and not existing.done():
        # 已有同名任务在跑:复用,防止两个任务并发写同一文档的向量与状态
        return existing
    # 任务已结束(done)则允许重新调度,支撑"重新入库"类操作
    task = asyncio.create_task(_track(document_id))
    _running[document_id] = task
    return task


# 任务收尾包装:无论成败都把文档从运行表摘除,避免完成后仍占位导致无法重新入库
async def _track(document_id: str) -> None:
    try:
        await run_ingestion(document_id)
    finally:
        # finally 保证失败、取消等异常路径同样得到清理
        _running.pop(document_id, None)
