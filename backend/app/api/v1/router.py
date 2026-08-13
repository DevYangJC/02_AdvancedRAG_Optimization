"""v1 路由汇总。"""
# v1 路由聚合点:新增功能模块时在这里挂载一次即可接入主应用
from fastapi import APIRouter

from app.api.v1 import auth, chat, conversations, documents, health

# 统一 /api 前缀:所有 v1 接口都在 /api 下,网关/反向代理可按前缀分流
api_router = APIRouter(prefix="/api")
# 挂载顺序即 OpenAPI 文档中的分组顺序;health 最前,纯文本探活接口响应最快
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(conversations.router)
# chat 与 documents 是知识库问答核心模块,与其余模块平级挂载
api_router.include_router(chat.router)
api_router.include_router(documents.router)
