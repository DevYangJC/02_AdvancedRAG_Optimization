"""pytest 全局配置:测试专用环境变量必须在导入 app 之前设置。

- 独立测试数据库(backend/data/test.db)
- 独立上传目录
- 测试专用 JWT secret
"""
import os
import sys
from pathlib import Path

# 必须在任何 app 模块导入前设置(settings 为 lru_cache 单例)
# 测试环境隔离四件套:独立数据库、独立上传目录、独立 JWT 密钥、禁用真实模型 Key,
# 任何一项缺失都会让测试污染开发数据或意外调用付费 API。
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./data/test.db"
# 独立测试库:用相对路径的 sqlite 文件,绝不触碰开发用的真实数据库文件。
os.environ["UPLOAD_DIR"] = "./data/test_uploads"
os.environ["JWT_SECRET"] = "test-secret-for-pytest"
os.environ["DASHSCOPE_API_KEY"] = ""

# 保证 backend 根目录在 sys.path(以 tests 目录的上级)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio  # noqa: E402
import uuid  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.session import async_session_maker, engine, init_db  # noqa: E402
# 导入真实的应用实例:测试走的就是生产同一条 FastAPI 路由,而不是复制一份逻辑。
from app.main import app  # noqa: E402
from app.services.bootstrap import ensure_dirs, seed_admin  # noqa: E402


# 唯一用户名:测试库是持久化的,没有唯一后缀的话,第二次跑测试就会因重名注册返回 400。
def unique_name(prefix: str = "user") -> str:
    """生成唯一用户名,保证测试可重复运行(测试库持久化)。"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


# 会话级夹具(整个测试会话只执行一次):统一完成建目录、建库、写种子账号,
# 让各测试方法不用关心初始化细节,专注自己的断言。
@pytest.fixture(scope="session", autouse=True)
def _prepare_env():
    # 测试环境禁用限流(否则全量测试的注册次数会触发 429)
    from app.core.limiter import limiter

    limiter.enabled = False

    # 建上传目录:部分加载器测试会真实写文件,目录必须先存在。
    ensure_dirs()
    # init_db 是异步函数,而 fixture 本身是同步的,用 asyncio.run 包一层执行。
    asyncio.run(init_db())
    async def _seed():
        # 种子 admin 账号由 seed_admin 幂等创建,供权限类测试复用。
        async with async_session_maker() as db:
            await seed_admin(db)
    asyncio.run(_seed())
    yield
    # 测试全部结束后释放连接池,否则 pytest 进程退出时可能残留告警。
    asyncio.run(engine.dispose())


# httpx 的异步测试客户端:通过 ASGI 传输层直连应用,不开真实端口,
# 比"起服务再 HTTP 访问"快得多,也不依赖端口占用情况。
@pytest_asyncio.fixture
async def client():
    """httpx AsyncClient(不触发 lifespan,数据库已手动初始化)。"""
    # ASGITransport 把 HTTP 请求映射成 ASGI 调用,等价于"内存里的真实请求"。
    transport = ASGITransport(app=app)
    # base_url 用占位域名:httpx 只拿它拼路径,实际不会发起网络请求。
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# 返回种子管理员 admin 的 JWT:管理接口测试的第一行基本都是"取 token 再带请求头"。
@pytest_asyncio.fixture
async def admin_token(client: AsyncClient):
    # 密码是种子账号默认值 123456,仅存在于测试环境(见 seed_admin 脚本)。
    resp = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    assert resp.status_code == 200
    return resp.json()["access_token"]


# 注册两个普通用户供隔离测试使用:越权场景必须有两个互不相干的账号。
@pytest_asyncio.fixture
async def user_tokens(client: AsyncClient):
    """注册两个普通用户,返回 (user_a_token, user_b_token)。"""

    # 内部辅助函数:注册并断言成功,失败时把响应文本带出来便于排查。
    async def _register(username: str):
        resp = await client.post(
            "/api/auth/register",
            json={"username": username, "password": "pass123456", "nickname": username},
        )
        # 断言失败时打印响应体:用户名撞车等注册失败原因一目了然。
        assert resp.status_code == 200, resp.text
        return resp.json()["access_token"]

    # 顺序注册即可:并发注册依赖注册接口的并发安全,没必要引入这类不确定性。
    return await _register(unique_name("user_a")), await _register(unique_name("user_b"))


# 构造带鉴权的请求头:JWT 走 Bearer 模式,与后端 FastAPI 依赖注入解析的标准一致。
def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
