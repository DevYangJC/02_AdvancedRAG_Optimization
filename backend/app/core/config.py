"""应用配置:从 .env / 环境变量读取,pydantic-settings 自动校验。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


# Settings 继承 pydantic-settings:字段声明即配置项,启动时从 .env 读取并自动校验类型
class Settings(BaseSettings):
    # 读取行为集中声明:extra=ignore 容忍 .env 里的多余键,case_sensitive=False 降低手写大小写错误的成本
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 阿里云百炼 DashScope(全链路云端) ---
    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-plus"
    embedding_model: str = "text-embedding-v3"
    embedding_dimensions: int = 1024
    reranker_model: str = "gte-rerank-v2"
    rerank_api_url: str = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"

    # --- LLM 并发与重试 ---
    # 并发超过 8 易触发百炼侧限流;重试 3 次让偶发超时不必用户手动重发
    llm_max_concurrency: int = 8
    llm_max_retries: int = 3

    # --- 数据库 ---
    # SQLite 零配置即可跑通本地开发;生产只需改此 URL 即可切换 MySQL/PostgreSQL(见 db/session.py)
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    # 连接池大小:高并发落库(问答/入库)同时占用多个会话,池太小会连接饥饿、请求排队
    db_pool_size: int = 10
    db_max_overflow: int = 10

    # --- Qdrant ---
    # Qdrant 是向量数据库,存文档切块的 embedding;collection 相当于"库中库",每个知识库可独立管理
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "product_docs"

    # --- 检索参数 ---
    # 先粗召回 100 条(便宜、快),再经 rerank 精排到 6 条:召回率与精排成本折中
    retrieve_dense_top_k: int = 100
    rerank_top_n: int = 6
    rerank_batch_size: int = 32

    # --- 切分 ---
    # 切分粒度影响检索精度:500 字左右上下文信息最完整;overlap 让跨块语义不被切断
    chunk_size: int = 500
    chunk_overlap: int = 50

    # --- 缓存 ---
    # 语义缓存 TTL 24 小时:命中直接复用答案省一次 LLM 调用;后台定时清理过期条目防表无限膨胀
    cache_ttl_hours: int = 24
    cache_cleanup_interval_min: int = 30

    # --- 认证 ---
    # JWT(JSON Web Token)是签名式无状态登录凭证;密钥泄露等于可伪造任意用户身份,生产必须改随机长串
    jwt_secret: str = "change-me-to-a-long-random-string"
    jwt_algorithm: str = "HS256"
    # 双 token 策略:access 短效(2 小时)随请求携带,refresh 长效(14 天)只用于换新,见 core/security.py
    jwt_access_expire_minutes: int = 120
    jwt_refresh_expire_days: int = 14
    admin_username: str = "admin"
    admin_password: str = "123456"

    # --- 上传 ---
    # 上传双重限制:大小上限防磁盘耗尽,扩展名白名单防可执行/恶意文件混入知识库
    upload_max_size_mb: int = 50
    allowed_extensions: str = "pdf,docx,xlsx,txt,md"
    upload_dir: str = "./data/uploads"

    # --- 会话 ---
    # 多轮问答拼接最近 N 条历史做上下文:太少答非所问,太多挤占 token 预算
    history_messages: int = 10

    # --- 压测模式 ---
    # 压测时设为 false 禁用限流:压测机从同一 IP 发出高频请求,限流会误伤
    rate_limit_enabled: bool = True

    # 只读属性:启动日志与前端用它提示"未配置 API Key",避免运行到问答时才报错
    @property
    def api_key_configured(self) -> bool:
        return bool(self.dashscope_api_key)


# lru_cache 保证全局只有一份配置实例:避免每处调用都重新读 .env 与磁盘
@lru_cache
def get_settings() -> Settings:
    return Settings()


# 模块级单例:业务代码直接 import settings 使用,无需手动调用 get_settings
settings = get_settings()


settings = get_settings()
