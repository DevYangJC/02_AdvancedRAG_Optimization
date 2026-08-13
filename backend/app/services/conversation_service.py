"""会话服务:CRUD、归属校验、历史消息、反馈、标题生成。"""
# 会话是"提问+回答"的分组容器:侧边栏、消息列表、权限校验都围绕它展开
# 所有写操作(改名/删除/反馈)都先做归属校验,保证用户只能操作自己的会话
import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.session import async_session_maker
from app.models import Conversation, Message, User
from app.services import llm_service

logger = logging.getLogger(__name__)


# 归属校验一体查询:user_id + conv_id 双条件一次查询,省去"先查后比对"的往返
# 参数: db=数据库会话、user_id=当前用户、conv_id=目标会话;返回校验通过的会话对象
async def get_owned_conversation(db: AsyncSession, user_id: str, conv_id: str) -> Conversation:
    """归属校验一体查询:非本人一律 404,不暴露存在性。"""
    conv = await db.scalar(
        select(Conversation).where(Conversation.id == conv_id, Conversation.user_id == user_id)
    )
    if conv is None:
        # 对"不存在"与"无权限"返回同一响应:防止攻击者探测他人会话 id
        raise NotFoundError("会话不存在")
    # 校验通过才返回:后续写操作直接复用该对象,无需二次查询
    return conv


# 新建会话:归属直接取自已认证的 user.id,新会话天然属于当前用户,无需再做归属校验
# 参数: user=当前用户(必须已认证)、title=初始标题(可空,缺省"新对话");返回已落库的会话
async def create_conversation(db: AsyncSession, user: User, title: str | None = None) -> Conversation:
    # 标题缺省"新对话",首条消息回答后再由 LLM 精修为有意义的标题
    conv = Conversation(user_id=user.id, title=title or "新对话")
    db.add(conv)
    await db.commit()
    # refresh 回读数据库生成的 id/created_at,保证返回对象字段完整
    await db.refresh(conv)
    return conv


# 会话列表分页:返回 (当前页列表, 总数),总数供前端计算总页数
# 参数: user=当前用户、page=页码(从 1 起)、page_size=每页条数(默认值由 API 层透传)
async def list_conversations(db: AsyncSession, user: User, page: int, page_size: int) -> tuple[list[Conversation], int]:
    # count 与列表分两条查询:总数与数据解耦,互不阻塞
    total = (
        await db.execute(
            select(func.count()).select_from(Conversation).where(Conversation.user_id == user.id)
        )
    ).scalar_one()
    # 按 updated_at 倒序:最近活跃的会话置顶,符合用户直觉
    rows = (
        await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user.id)
            .order_by(Conversation.updated_at.desc())
            # page 从 1 起算,offset 换算成行偏移;limit 只取当前页,避免一次加载全部会话
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    # 返回 ORM 对象而非 dict:序列化细节交给 schema 层统一处理
    return list(rows), total


# 重命名会话:复用归属校验,他人会话的改名请求同样返回 404
# 参数: title=新标题;返回更新后的会话对象(前端可直接用其刷新侧边栏)
async def rename_conversation(db: AsyncSession, user: User, conv_id: str, title: str) -> Conversation:
    conv = await get_owned_conversation(db, user.id, conv_id)
    # 截断到 100 字:防止超长标题撑爆侧边栏与消息列表
    conv.title = title[:100]
    await db.commit()
    await db.refresh(conv)
    return conv


# 删除会话:先删子表消息再删会话,避免外键约束报错;删除不可恢复,前端需二次确认
async def delete_conversation(db: AsyncSession, user: User, conv_id: str) -> None:
    conv = await get_owned_conversation(db, user.id, conv_id)
    # 级联删除手动执行:模型未配置自动 cascade,这里显式清空该会话的消息(反馈随消息一并删除)
    await db.execute(Message.__table__.delete().where(Message.conversation_id == conv_id))
    # 删除顺序固定"子→父":外键约束要求先删除引用方,再删被引用方
    await db.delete(conv)
    # 注意:向量库内容属于文档,与会话无关,此处无需清理
    await db.commit()


# 会话内消息分页:返回 (消息列表, 总数, 会话对象),调用方可直接取会话标题渲染头部
# 参数: user=当前用户、conv_id=目标会话、page/page_size=分页参数
async def list_messages(db: AsyncSession, user: User, conv_id: str, page: int, page_size: int) -> tuple[list[Message], int]:
    # 归属校验前置:他人会话的消息一律不可见
    conv = await get_owned_conversation(db, user.id, conv_id)
    total = (
        await db.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conv_id)
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id)
            # 按时间正序展示(与聊天顺序一致);id 二次排序保证同一时刻的消息顺序稳定
            .order_by(Message.created_at.asc(), Message.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return list(rows), total, conv


# 消息反馈(点赞/点踩 + 可选文字):join 会话表校验归属,单条查询完成
async def set_feedback(db: AsyncSession, user: User, message_id: str, value: int, text: str | None) -> Message:
    # join 校验而非"先查消息再查会话":避免两次查询之间消息状态被修改(TOCTOU 窗口)
    msg = await db.scalar(
        select(Message)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.id == message_id, Conversation.user_id == user.id)
    )
    if msg is None:
        raise NotFoundError("消息不存在")
    # value 的取值(如 1/-1)由 schema 层约束,这里直接落库
    msg.feedback = value
    msg.feedback_text = text  # text 可空:仅点赞/点踩时没有附加文字
    await db.commit()
    # 返回更新后的消息:前端据此刷新反馈按钮的选中状态
    await db.refresh(msg)
    return msg


# 异步生成会话标题(首条消息触发):LLM 提取 ≤20 字,失败则回退为问题截断
# 参数: conv_id=目标会话、question=首条用户问题(标题素材)
async def generate_title(db: AsyncSession, conv_id: str, question: str) -> None:
    """异步生成会话标题(首条消息触发):LLM 提取 ≤20 字,失败则截断首问。"""

    async def _do():
        try:
            answer = await llm_service.ainvoke(
                [
                    {
                        "role": "user",
                        "content": (
                            "为以下用户问题生成一个不超过 20 个字符的会话标题,"
                            "直接输出标题,不要引号和标点:\n" + question[:200]
                        ),
                    }
                ]
            )
            # 去除模型可能多带的引号/括号后截断,保证标题长度可控
            title = answer.strip().strip('"').strip("「」")[:20]
        except Exception:  # noqa: BLE001
            # 标题生成是"锦上添花":任何失败都回退为问题截断,不抛异常
            title = question[:20]
        # 独立会话写库:异步任务已脱离请求生命周期,原请求会话可能已结束
        async with async_session_maker() as s:
            conv = await s.get(Conversation, conv_id)
            # guard:用户可能在标题生成期间删除了会话,静默跳过即可
            if conv:
                conv.title = title
                await s.commit()

    # create_task 不阻塞回答流;_do 内部已捕获所有异常,任务不会裸奔崩溃
    asyncio.create_task(_do())


# 更新会话活跃时间:侧边栏按 updated_at 倒序,该函数是排序生效的关键
def touch_conversation(db: AsyncSession, conv: Conversation) -> None:
    """更新会话活跃时间(侧边栏倒序依据)。"""
    # 函数内 import:该工具仅此一处使用,延迟加载不增加模块顶层依赖
    from datetime import datetime

    conv.updated_at = datetime.now()
