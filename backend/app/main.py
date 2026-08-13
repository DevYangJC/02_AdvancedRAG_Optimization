"""FastAPI 应用入口。

启动流程(lifespan):
  1. 初始化日志与目录
  2. 建表 + 种子管理员
  3. Qdrant 连接检查 + collection 就绪
  4. 后台启动缓存清理任务
"""
# 应用组装集中在本文件:路由、中间件、异常处理器一览无余,新人看这一个文件即可了解全局
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import AppError, error_body
from app.core.logging import RequestIDMiddleware, setup_logging
from app.db.session import async_session_maker, init_db
from app.services import cache_service, vector_service
from app.services.bootstrap import ensure_dirs, seed_admin

logger = logging.getLogger(__name__)


# 后台守护任务:独立循环周期执行,异常必须兜底,否则任务会静默死亡
async def _cache_cleanup_loop() -> None:
    """周期性清理过期语义缓存条目。"""
    # 常驻循环:配合 create_task 在 lifespan 内运行,进程退出时随任务取消而停止
    while True:
        try:
            # 每次清理独立开新会话,避免长会话持有陈旧数据与连接
            async with async_session_maker() as db:
                removed = await cache_service.cleanup_expired(db)
                # 只有实际删除了条目才打日志,避免每分钟无意义刷日志
                if removed:
                    logger.info("清理过期缓存 %d 条", removed)
        except Exception as e:  # noqa: BLE001
            # 清理失败(如数据库临时不可用)不能拖垮整个任务,记录警告后继续下一轮
            logger.warning("缓存清理任务异常: %s", e)
        # 用 sleep 而非精确计时:允许清理延迟,避免与请求高峰期重叠
        await asyncio.sleep(settings.cache_cleanup_interval_min * 60)


# lifespan 上下文替代废弃的 @app.on_event 写法:启动与关闭逻辑集中一处,顺序清晰可控
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 先日志后建表:后续任何日志输出才有地方可去
    setup_logging()
    # 确保上传/日志目录存在,避免运行期 FileNotFoundError
    ensure_dirs()
    # 建表与种子数据在同一会话完成,保证原子性
    async with async_session_maker() as db:
        await init_db()
        # 首次启动若无管理员则自动创建默认账号,避免空系统无法登录
        await seed_admin(db)

    # Qdrant 就绪检查 + collection 创建
    try:
        await vector_service.ensure_collection()
        logger.info("Qdrant 就绪: %s", settings.qdrant_url)
    except Exception as e:  # noqa: BLE001
        # 只记日志不退出:向量库故障不应导致整个 API 无法启动,认证/会话等主流程继续可用
        logger.error("Qdrant 连接失败(知识库功能不可用): %s", e)

    # 缓存清理任务后台运行;保留任务对象引用,防止被垃圾回收
    cleanup_task = asyncio.create_task(_cache_cleanup_loop())
    # 启动完成日志带 API Key 是否配置,部署时确认环境变量是否生效
    logger.info("服务启动完成, API Key 已配置: %s", settings.api_key_configured)

    # yield 之后是关闭阶段:FastAPI 收到停止信号后执行此处
    yield
    # 先取消后台任务再关资源:顺序反过来可能让清理逻辑写到半关闭的连接
    cleanup_task.cancel()
    await vector_service.close_client()
    # 延迟导入:避免启动阶段加载重模型;此处只为关闭其 HTTP 连接
    from app.rag import reranker

    await reranker.close_client()
    logger.info("服务已关闭")


# FastAPI 实例是模块级单例:uvicorn 直接 import app,多 worker 时各自持有独立实例
app = FastAPI(
    title="LangChain RAG 知识库问答系统",
    version="1.0.0",
    lifespan=lifespan,
    # 文档与 OpenAPI 路径放在 /api 前缀下:便于网关统一路由与鉴权
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

# --- 限流(slowapi):按 IP 限流,防刷与成本保护 ---
# 延迟到函数外导入:避免 core.limiter 与路由形成循环依赖
from slowapi import _rate_limit_exceeded_handler  # noqa: E402
from slowapi.errors import RateLimitExceeded  # noqa: E402

from app.core.limiter import limiter  # noqa: E402

# 限流器实例挂在 app.state:slowapi 依赖此属性读取计数,装饰器与实例同源才生效
app.state.limiter = limiter
# 压测模式(RATE_LIMIT_ENABLED=false)禁用限流:压测机同 IP 高频请求会误触 429
if not settings.rate_limit_enabled:
    limiter.enabled = False
    logger.warning("限流已禁用(压测模式)")
# 限流异常单独注册处理器,返回 429 而非默认的 500
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# 中间件按添加顺序执行:RequestID 在最外层,所有后续处理(含其他中间件)都能带请求 id
app.add_middleware(RequestIDMiddleware)
# CORS:浏览器同源策略下,前端(5173)跨端口调用必须显式放行;allow_credentials=True 时不能配 * 来源
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 汇总挂载所有 v1 子路由,新增模块只需在 router.py 注册一次
app.include_router(api_router)


# 业务异常统一走 JSON 响应:前端用同一错误体结构解析,无需区分每个接口
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=error_body(exc))


# 兜底:未预期异常也返回 JSON 而非 HTML 堆栈页,同时完整记录堆栈便于排查
@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    # logger.exception 自动附带堆栈;记录请求方法与路径,可快速定位是哪个接口出的问题
    logger.exception("未处理异常: %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"code": "INTERNAL_ERROR", "message": "服务器内部错误", "detail": str(exc)},
    )
