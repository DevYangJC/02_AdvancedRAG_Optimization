"""异步数据库引擎与会话工厂。

- SQLite:开启 WAL + 外键 + busy_timeout,连接池 5+5
- 生产切 MySQL/PostgreSQL 只需改 settings.database_url
"""
import logging

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# 模块级 logger:init_db 等函数记录日志时自动带上模块名,便于定位问题出自哪个模块
logger = logging.getLogger(__name__)


# 工厂函数而非直接写死:便于测试时传入不同 URL 构造独立引擎,互不影响
def _make_engine():
    connect_args = {}
    # 非 SQLite 驱动(如 psycopg)不接受 timeout 参数,按数据库类型分开传参
    if settings.database_url.startswith("sqlite"):
        # SQLite 并发写会锁库,timeout=30 让连接等待锁释放而非立刻报错
        connect_args = {"timeout": 30}
    return create_async_engine(
        settings.database_url,
        # echo=False 关闭 SQL 日志,避免生产环境刷屏与敏感数据外泄
        echo=False,
        # 池化复用连接:异步驱动下每次建连开销大;池大小可配置(压测时调大防连接饥饿)
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # 每次取连接先探活,剔除死连接,防止数据库重启后请求报错
        pool_pre_ping=True,
        connect_args=connect_args,
    )


# 模块级单例引擎:整个进程共享同一连接池,禁止在函数内重复创建
engine = _make_engine()


# WAL 等 PRAGMA 是 SQLite 特有,只有连 SQLite 时才注册事件监听,避免影响其他数据库
if settings.database_url.startswith("sqlite"):

    # 连接建立事件:每次新建连接都自动执行,保证每个连接都带上相同配置
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        # WAL(预写日志)模式:读写互不阻塞,显著提升并发性能
        cursor.execute("PRAGMA journal_mode=WAL")
        # SQLite 默认不启用外键约束,显式开启才能让 ON DELETE 等约束生效
        cursor.execute("PRAGMA foreign_keys=ON")
        # 多线程写时让连接等待锁释放,而不是立刻返回 "database is locked"
        cursor.execute("PRAGMA busy_timeout=30000")
        # 及时释放游标,避免连接句柄泄漏
        cursor.close()


# expire_on_commit=False:提交后对象属性仍可读,避免异步上下文中触发隐式刷新(会报 MissingGreenlet)
async_session_maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# create_all 幂等:只创建不存在的表,重复调用安全;生产环境建议换 Alembic 迁移管理表结构变更
async def init_db() -> None:
    """建表(开发期直接 create_all;生产可用 Alembic 迁移)。"""
    from sqlalchemy import text  # 延迟导入,避免顶层依赖

    from app.db.base import Base
    from app.models import CacheEntry, Chunk, Conversation, Document, EvalRecord, EvalTask, Message, User  # noqa: F401 注册模型

    # begin() 保证建表在单个事务内完成,失败自动回滚,不留半成品表
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all 只建新表、不改已有表:SQLite 下手动补加后续新增的可空列
        # 列已存在时 ALTER 会报 "duplicate column name",吞掉即可(幂等)
        try:
            await conn.execute(text("ALTER TABLE eval_tasks ADD COLUMN review TEXT"))
            logger.info("已为 eval_tasks 补充 review 列")
        except Exception:
            pass  # 列已存在(或非 SQLite),忽略
    # 启动日志:确认表结构就绪,排查"表不存在"问题时能一眼定位
    logger.info("数据库表结构已就绪")
