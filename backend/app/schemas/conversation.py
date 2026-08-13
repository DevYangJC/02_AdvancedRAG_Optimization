"""会话与消息请求/响应模型。"""
# 字段即前后端联调的契约;列表结构统一为 items + 分页信息,前端可一套组件复用
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# 会话出参:不含消息体,列表页只需标题与时间;from_attributes 支持 ORM 对象直转
class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# 分页结构统一:total 供前端渲染总页数,page/page_size 原样回传避免猜测
class ConversationListOut(BaseModel):
    items: list[ConversationOut]
    total: int
    page: int
    page_size: int


# 创建会话可带标题:不传则服务端用默认"新对话";100 字上限与数据库定义一致
class ConversationCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=100)


# 重命名必须传新标题:min_length=1 直接拦截空标题
class ConversationUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=100)


# 引用来源单条结构:与 Message 表 sources JSON 字段一一对应,保证存储与返回一致
class SourceRef(BaseModel):
    # 序号:前端按此排序展示引用列表
    index: int
    doc_id: str
    # 冗余存标题快照:文档删除/改名后,历史引用仍可展示
    doc_title: str
    page: int | None = None
    section: str | None = None
    snippet: str
    # 重排得分:展示相关度,也可让前端按分数排序
    score: float


# 消息出参:含 sources/status/feedback,前端渲染整条对话无需二次查询
class MessageOut(BaseModel):
    id: str
    # 归属会话 id:前端按此定位所属会话,删除/编辑时作为主键使用
    conversation_id: str
    # role 决定渲染靠左(用户)还是靠右(助手)
    role: str
    content: str
    sources: list[Any] | None
    # completed 正常 / error 中断,前端据此提示"回答不完整"
    status: str
    feedback: int | None
    token_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


# 历史消息分页:长对话分批拉取,避免单次响应过大
class MessageListOut(BaseModel):
    # 列表按创建时间倒序返回,前端无需自行排序
    items: list[MessageOut]
    total: int
    page: int
    page_size: int


# 反馈请求:value 用 ge/le 限定在 -1/0/1(0 表示取消反馈);text 为可选补充说明
class FeedbackRequest(BaseModel):
    value: int = Field(ge=-1, le=1, description="1 好 / -1 差")
    # 补充意见 500 字内,与 Message 表 feedback_text 列定义一致
    text: str | None = Field(default=None, max_length=500)


# 对话请求:conversation_id 为空则新建会话,非空则续接该会话
class ChatRequest(BaseModel):
    conversation_id: str | None = None  # 为空则自动新建会话
    # 问题长度 1-4000:过短无意义,过长会撑爆上下文窗口
    content: str = Field(min_length=1, max_length=4000)
    # 限定检索范围:传了则只在这些文档里召回,不传则全库召回
    doc_ids: list[str] | None = None  # 可选:限定知识库文档
