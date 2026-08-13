"""问答接口:POST /chat/stream(SSE 流式)。

事件协议:event: meta / delta / done / error,data 为 JSON。
注意:sse-starlette 的 EventSourceResponse 期望 yield dict(会自动拼装 event:/data: 帧),
不能直接 yield 已拼好的字符串,否则会产生双重包装导致前端无法解析。
"""
import json
import logging

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from app.core.deps import CurrentUser, DbDep
from app.core.limiter import limiter
from app.schemas.conversation import ChatRequest
from app.services import chat_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


def _sse_event(event_type: str, data: dict) -> dict:
    return {"event": event_type, "data": json.dumps(data, ensure_ascii=False)}


@router.post("/stream")
@limiter.limit("30/minute")
async def chat_stream(request: Request, body: ChatRequest, db: DbDep, user: CurrentUser):
    async def event_gen():
        try:
            async for ev in chat_service.stream_chat(db, user, body):
                yield _sse_event(ev["type"], ev["data"])
        except Exception as e:  # noqa: BLE001 兜底:任何未捕获异常转为 error 事件
            logger.exception("SSE 流异常")
            yield _sse_event("error", {"code": "INTERNAL_ERROR", "message": f"服务器内部错误: {e}"})

    return EventSourceResponse(
        event_gen(),
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
