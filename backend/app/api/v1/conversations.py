"""会话接口:CRUD、历史消息分页、消息反馈。所有接口仅限本人会话。"""
# 数据严格按用户隔离:"owned" 校验下沉在 service 层,路由只做取参与组响应
from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbDep
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationListOut,
    ConversationOut,
    ConversationUpdateRequest,
    FeedbackRequest,
    MessageListOut,
    MessageOut,
)
from app.services import conversation_service

# 路由保持"薄":所有业务判断(归属、权限、分页)都在 service 层完成
router = APIRouter(prefix="/conversations", tags=["conversations"])


# 会话列表:分页参数 Query 默认 1/50,前端滚动加载时传 page
@router.get("", response_model=ConversationListOut)
async def list_conversations(
    db: DbDep,
    # CurrentUser 依赖在函数体执行前完成 token 校验,未登录请求进不来
    user: CurrentUser,
    # ge=1 拒绝非法页码(0 或负数),接口层就拦截而非等 service 报错
    page: int = Query(1, ge=1),
    # 上限 100:防止一次拉取过多,前端可调整页大小
    page_size: int = Query(50, ge=1, le=100),
):
    # service 返回 (items, total):total 供前端渲染总数/总页数
    items, total = await conversation_service.list_conversations(db, user, page, page_size)
    # 分页参数原样回传:前端无需再猜当前页
    return ConversationListOut(items=items, total=total, page=page, page_size=page_size)


# 创建会话:title 为空时 service 用默认"新对话";返回完整对象供前端直接使用
@router.post("", response_model=ConversationOut)
async def create_conversation(body: ConversationCreateRequest, db: DbDep, user: CurrentUser):
    # body 自动校验:title 超 100 字返回 400,规则见 schemas/conversation.py
    return await conversation_service.create_conversation(db, user, body.title)


# 详情:get_owned_conversation 内部校验归属,他人会话一律 404(不暴露存在性)
@router.get("/{conv_id}", response_model=ConversationOut)
async def get_conversation(conv_id: str, db: DbDep, user: CurrentUser):
    # "owned" 语义:按 user_id=当前用户 AND id=conv_id 查询,天然防越权
    return await conversation_service.get_owned_conversation(db, user.id, conv_id)


# 重命名:只改 title;updated_at 自动刷新,列表按此上浮
@router.put("/{conv_id}", response_model=ConversationOut)
async def rename_conversation(conv_id: str, body: ConversationUpdateRequest, db: DbDep, user: CurrentUser):
    return await conversation_service.rename_conversation(db, user, conv_id, body.title)


# 删除:级联删除消息与引用(见 service);返回 {ok:true} 即可,前端收到后刷新列表
@router.delete("/{conv_id}")
async def delete_conversation(conv_id: str, db: DbDep, user: CurrentUser):
    await conversation_service.delete_conversation(db, user, conv_id)
    return {"ok": True}


# 历史消息:分页 1/200;长对话分批拉取,避免单次响应过大
@router.get("/{conv_id}/messages", response_model=MessageListOut)
async def list_messages(
    conv_id: str,
    db: DbDep,
    user: CurrentUser,
    page: int = Query(1, ge=1),
    # 消息页大小上限 200:对话可能很长,200 一页兼顾加载量与性能
    page_size: int = Query(50, ge=1, le=200),
):
    # _ 丢弃第三个返回值(如未读数),Python 惯例命名
    items, total, _ = await conversation_service.list_messages(db, user, conv_id, page, page_size)
    return MessageListOut(items=items, total=total, page=page, page_size=page_size)


# 反馈接口挂在会话路由下,message_id 归属校验在 service 完成
@router.post("/messages/{message_id}/feedback")
async def set_feedback(message_id: str, body: FeedbackRequest, db: DbDep, user: CurrentUser):
    # value 由 FeedbackRequest 限定 -1/0/1;返回最新值供前端回显
    msg = await conversation_service.set_feedback(db, user, message_id, body.value, body.text)
    return {"ok": True, "feedback": msg.feedback}
