"""健康检查:DB / Qdrant / 模型 API 三探针。"""
import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.deps import DbDep

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(db: DbDep):
    probes = {"status": "ok"}

    # DB 探针
    try:
        await db.execute(text("SELECT 1"))
        probes["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        probes["db"] = f"error: {e}"

    # Qdrant 探针
    try:
        from app.services.vector_service import ping_qdrant

        probes["qdrant"] = "ok" if await ping_qdrant() else "error: unreachable"
    except Exception as e:  # noqa: BLE001
        probes["qdrant"] = f"error: {e}"

    # 模型 API 探针
    probes["models"] = "ok" if settings.api_key_configured else "warning: DASHSCOPE_API_KEY 未配置"

    if probes["db"] != "ok" or probes["qdrant"] != "ok":
        probes["status"] = "degraded"
    return probes
