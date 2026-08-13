# 模型聚合入口:统一从这里导出,其他模块只 import app.models,避免 import 路径散落各处
# db/session.py 的 init_db 也通过 import 本文件让模型注册进 metadata,create_all 才会建这些表
from app.models.cache_entry import CacheEntry
from app.models.chunk import Chunk
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.message import Message
from app.models.user import User

# __all__ 限定 from app.models import * 的可见范围,同时作为"公开 API"清单
__all__ = ["User", "Conversation", "Message", "Document", "Chunk", "CacheEntry"]
