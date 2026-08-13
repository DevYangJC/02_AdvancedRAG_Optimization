"""100 人并发压力测试脚本(httpx 异步,零额外依赖)。

前提:
  1. Qdrant + 后端已启动(压测模式:RATE_LIMIT_ENABLED=false 禁用限流)
  2. 知识库已上传测试文档
  3. 阿里云 API Key 已配置

场景:
  A 登录风暴    :N 用户同时登录(压 bcrypt + JWT)
  B 常规浏览    :N 用户并发拉会话列表/历史(压 API 与数据库读)
  C 并发问答    :30% 用户同时提问(完整 RAG 链路:检索-重排-LLM 流式-落库)
  D 混合 5 分钟 :N 用户持续混合行为(30% 提问 + 70% 浏览),测长期稳定性

用法:
  python -m scripts.load_test --users 100 --duration 300
"""
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

BASE = "http://localhost:8000"
PASSWORD = "load123456"
QUESTIONS = [
    "星云手机 X1 支持几天无理由退换?",
    "星云手机 X1 的电池容量是多少?",
    "星云手机 X1 支持多少瓦快充?",
    "清风空气净化器适用多大面积?",
    "星云手机 X1 的防水等级是什么?",
    "星云手机 X1 的售价是多少?",
    "星云蓝牙耳机 Pro 的续航怎么样?",
    "清风空气净化器的噪音是多少?",
    "星云手机 X1 的屏幕尺寸多大?",
    "清风空气净化器的滤芯多久换一次?",
    "星云蓝牙耳机 Pro 支持降噪吗?",
    "星云手机 X1 的摄像头像素是多少?",
    "星云手机 X1 支持无线充电吗?",
    "清风空气净化器的功率是多少?",
    "星云蓝牙耳机 Pro 的防水等级?",
    "星云手机 X1 保修政策是什么?",
]


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = min(len(values) - 1, int(len(values) * p))
    return round(values[idx], 1)


def report_row(name: str, lat: list[float], qps: float, errors: int) -> None:
    print(
        f"  {name:<22} P50={percentile(lat, 0.5):>8.1f}ms  "
        f"P95={percentile(lat, 0.95):>8.1f}ms  P99={percentile(lat, 0.99):>8.1f}ms  "
        f"QPS={qps:>6.1f}  错误={errors}"
    )


async def register_user(client: httpx.AsyncClient, username: str) -> None:
    """幂等注册:已存在则忽略(400)。"""
    resp = await client.post(
        "/api/auth/register", json={"username": username, "password": PASSWORD}
    )
    if resp.status_code not in (200, 400):
        print(f"  [警告] 注册 {username} 失败: {resp.status_code}")


async def login(client: httpx.AsyncClient, username: str) -> str | None:
    resp = await client.post(
        "/api/auth/login", json={"username": username, "password": PASSWORD}
    )
    if resp.status_code == 200:
        return resp.json()["access_token"]
    return None


async def chat_once(client: httpx.AsyncClient, token: str, question: str) -> tuple[float, float, bool]:
    """发起一次 SSE 问答,返回 (首 token 延迟 ms, 完整耗时 ms, 是否成功)。"""
    headers = {"Authorization": f"Bearer {token}"}
    start = time.perf_counter()
    first_token = None
    full_text = ""
    ok = False
    try:
        async with client.stream(
            "POST", "/api/chat/stream",
            json={"conversation_id": None, "content": question}, headers=headers,
        ) as resp:
            if resp.status_code != 200:
                return 0.0, (time.perf_counter() - start) * 1000, False
            async for raw in resp.aiter_bytes():
                if first_token is None:
                    first_token = (time.perf_counter() - start) * 1000
                full_text += raw.decode("utf-8", errors="ignore")
            ok = "event: done" in full_text and len(full_text) > 50
    except Exception:  # noqa: BLE001
        ok = False
    return first_token or 0.0, (time.perf_counter() - start) * 1000, ok


# ---------- 场景 ----------

async def scenario_a_login_storm(client: httpx.AsyncClient, users: list[str], concurrency: int) -> None:
    print(f"\n[场景 A] 登录风暴: {len(users)} 用户同时登录")
    lat: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)

    async def worker(username: str):
        nonlocal errors
        async with sem:
            start = time.perf_counter()
            token = await login(client, username)
            lat.append((time.perf_counter() - start) * 1000)
            if token is None:
                errors += 1

    start = time.perf_counter()
    await asyncio.gather(*[worker(u) for u in users])
    total = time.perf_counter() - start
    report_row("POST /auth/login", lat, len(users) / total, errors)


async def scenario_b_browse(
    client: httpx.AsyncClient, users: list[str], tokens: dict[str, str], concurrency: int
) -> None:
    print(f"\n[场景 B] 常规浏览: {len(users)} 用户并发浏览")
    lat: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)

    async def worker(username: str):
        nonlocal errors
        async with sem:
            headers = {"Authorization": f"Bearer {tokens[username]}"}
            start = time.perf_counter()
            resp = await client.get("/api/conversations", headers=headers)
            lat.append((time.perf_counter() - start) * 1000)
            if resp.status_code != 200:
                errors += 1

    start = time.perf_counter()
    await asyncio.gather(*[worker(u) for u in users])
    total = time.perf_counter() - start
    report_row("GET /conversations", lat, len(users) / total, errors)


async def scenario_c_concurrent_chat(
    client: httpx.AsyncClient, users: list[str], tokens: dict[str, str], concurrency: int
) -> None:
    print(f"\n[场景 C] 并发问答: {concurrency} 用户同时提问(完整 RAG 链路)")
    first_tokens: list[float] = []
    full_times: list[float] = []
    errors = 0
    sem = asyncio.Semaphore(concurrency)

    async def worker(i: int):
        nonlocal errors
        async with sem:
            username = users[i % len(users)]
            question = QUESTIONS[i % len(QUESTIONS)]
            ft, ftime, ok = await chat_once(client, tokens[username], question)
            first_tokens.append(ft)
            full_times.append(ftime)
            if not ok:
                errors += 1

    start = time.perf_counter()
    await asyncio.gather(*[worker(i) for i in range(concurrency)])
    total = time.perf_counter() - start
    print(f"  首 token 延迟:")
    report_row("  首 token", first_tokens, 0, 0)
    print(f"  完整问答:")
    report_row("  完整耗时", full_times, concurrency / total, errors)
    print(f"  完成率: {(concurrency - errors) / concurrency * 100:.1f}%")


async def scenario_d_mixed(
    client: httpx.AsyncClient, users: list[str], tokens: dict[str, str], duration: int
) -> None:
    """混合场景:30% 提问 + 70% 浏览,持续 duration 秒。"""
    print(f"\n[场景 D] 混合持续 {duration}s: {len(users)} 用户,30% 提问 + 70% 浏览")
    chat_lat: list[float] = []
    browse_lat: list[float] = []
    errors = 0
    total_ops = 0
    chat_ops = 0
    sem = asyncio.Semaphore(60)  # 总并发上限 60,防本机压测机自身成为瓶颈
    start_time = time.perf_counter()
    deadline = time.time() + duration

    async def do_chat(username: str, question: str):
        nonlocal errors, total_ops, chat_ops
        async with sem:
            ft, ftime, ok = await chat_once(client, tokens[username], question)
            chat_lat.append(ftime)
            chat_ops += 1
            total_ops += 1
            if not ok:
                errors += 1

    async def do_browse(username: str):
        nonlocal errors, total_ops
        async with sem:
            headers = {"Authorization": f"Bearer {tokens[username]}"}
            start = time.perf_counter()
            resp = await client.get("/api/conversations", headers=headers)
            browse_lat.append((time.perf_counter() - start) * 1000)
            total_ops += 1
            if resp.status_code != 200:
                errors += 1

    tasks: list[asyncio.Task] = []
    i = 0
    while time.time() < deadline:
        # 30% 用户提问、70% 浏览(按轮次调度,模拟真实使用节奏)
        for u in users:
            if time.time() >= deadline:
                break
            if i % 10 < 3:
                tasks.append(asyncio.create_task(do_chat(u, QUESTIONS[i % len(QUESTIONS)])))
            else:
                tasks.append(asyncio.create_task(do_browse(u)))
            i += 1
        await asyncio.sleep(0.2)  # 控制发起节奏,避免瞬间洪峰
    await asyncio.gather(*tasks, return_exceptions=True)

    total = time.perf_counter() - start_time
    print(f"  总操作数: {total_ops} | 问答 {chat_ops} | 浏览 {total_ops - chat_ops}")
    report_row("  问答耗时", chat_lat, chat_ops / total, errors)
    report_row("  浏览耗时", browse_lat, (total_ops - chat_ops) / total, 0)
    print(f"  错误率: {errors / total_ops * 100:.2f}%")


async def main() -> None:
    global BASE

    parser = argparse.ArgumentParser(description="LangChainRAG 100 人压力测试")
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--users", type=int, default=100, help="模拟用户数")
    parser.add_argument("--duration", type=int, default=300, help="场景 D 持续时间(秒)")
    args = parser.parse_args()

    BASE = args.base
    print(f"=== 压测目标 {BASE} | 用户数 {args.users} | 场景 D 持续 {args.duration}s ===")

    # ---- 0. 预置:注册 N 个测试用户 ----
    print("\n[0] 预置测试用户")
    users = [f"load_user_{i:03d}" for i in range(1, args.users + 1)]
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        await asyncio.gather(*[register_user(c, u) for u in users])
    print(f"  已就绪 {len(users)} 个用户(load_user_001 ~ load_user_{args.users:03d})")

    # 全部登录拿 token
    tokens: dict[str, str] = {}
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as c:
        results = await asyncio.gather(*[login(c, u) for u in users])
    for u, t in zip(users, results):
        if t:
            tokens[u] = t
    print(f"  登录成功 {len(tokens)}/{len(users)}")

    # ---- 场景 A-D(共享连接池,真实客户端行为) ----
    async with httpx.AsyncClient(base_url=BASE, timeout=180, limits=httpx.Limits(max_connections=100)) as shared:
        await scenario_a_login_storm(shared, users[:100], concurrency=100)
        await scenario_b_browse(shared, list(tokens.keys()), tokens, concurrency=100)
        await scenario_c_concurrent_chat(shared, list(tokens.keys()), tokens, concurrency=int(len(tokens) * 0.3))
        await scenario_d_mixed(shared, list(tokens.keys()), tokens, args.duration)

    print("\n=== 压测完成 ===")


if __name__ == "__main__":
    asyncio.run(main())
