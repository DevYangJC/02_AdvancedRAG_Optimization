"""性能压测脚本:对运行中的后端做并发问答与接口延迟测试。

用法(先启动后端与 qdrant):
    python -m scripts.perf_test --base http://localhost:8000 --concurrency 5 --questions 10

输出:接口 P50/P95/P99 延迟、首 token 延迟、缓存命中对比、并发正确性检查。
"""
# ---------------------------------------------------------------------------
# 性能压测脚本:对运行中的后端做并发问答与接口延迟测试。
# 与 e2e_smoke.py 关注"功能是否正确"不同,这里只关心"快不快":
# 输出 P50/P95/P99 延迟、首 token 延迟与缓存命中提速比。
# ---------------------------------------------------------------------------
import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

# 压测用的标准问题集:直接复用 create_test_data.py 的事实锚点,
# 保证每次压测检索的是同一批文档,结果才有可比性。
QUESTIONS = [
    "星云手机 X1 支持几天无理由退换?",
    "星云手机 X1 的电池容量是多少?",
    "星云手机 X1 支持多少瓦快充?",
    "清风空气净化器适用多大面积?",
    "星云手机 X1 的防水等级是什么?",
]


# 压测账号固定用种子管理员:压测只需要权限,不需要单独注册账号。
async def login(base: str) -> str:
    async with httpx.AsyncClient(base_url=base, timeout=10) as client:
        resp = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        resp.raise_for_status()
        # 登录接口直接返回 JWT,无需再查用户信息。
        return resp.json()["access_token"]


# 通用接口计时:返回 (耗时 ms, 响应),状态码由调用方自行断言。
# 用 perf_counter(单调时钟)而非 time.time:不受系统校时影响,计时更稳定。
async def measure_api(client: httpx.AsyncClient, method: str, url: str, **kw) -> tuple[float, httpx.Response]:
    start = time.perf_counter()
    # 用 request 泛化方法:同一计时逻辑可测任意 HTTP 动词,无需为每个动词写一遍。
    resp = await client.request(method, url, **kw)
    # 单位换算成毫秒:perf_counter 返回秒,与前端/监控的毫秒口径保持一致。
    elapsed = (time.perf_counter() - start) * 1000
    return elapsed, resp


# 发一次 SSE 流式问答,统计"首 token 延迟"与完整回答。
# 首 token 延迟 = 从发出请求到收到第一个字节的时间,是流式聊天体验的关键指标。
async def chat_once(client: httpx.AsyncClient, conv_id: str | None, question: str) -> tuple[float, str]:
    """发起一次 SSE 问答,返回 (首 token 延迟 ms, 完整回答)。"""
    start = time.perf_counter()
    first_token_at: float | None = None
    full_text = ""
    # 不预读全部响应:逐字节消费流,才能测出真实的"首 token"到达时间。
    async with client.stream(
        "POST", "/api/chat/stream", json={"conversation_id": conv_id, "content": question}
    ) as resp:
        resp.raise_for_status()
        buffer = ""
        async for raw in resp.aiter_bytes():
            if first_token_at is None and raw:
                # 第一个非空字节到达即记为首 token,之后不再覆盖。
                first_token_at = (time.perf_counter() - start) * 1000
            buffer += raw.decode("utf-8", errors="ignore")
        # 简单解析:提取所有 delta 的 text
        for frame in buffer.split("\n\n"):
            if "delta" in frame:
                try:
                    data = json.loads(frame.split("data:", 1)[1].strip())
                    full_text += data.get("text", "")
                except Exception:  # noqa: BLE001
                    # 压测目的是量延迟,单帧解析失败不影响计时,静默跳过。
                    pass
    return (first_token_at or 0.0), full_text


# 从样本中取分位值:p=0.95 表示 95% 的请求延迟不超过该值。
# 分位比平均值更能反映"绝大多数用户"的体验,不被个别长尾请求带偏。
def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    # 分位位置 = 样本数 × 分位,向下取整到有效下标(末尾兜底防越界)。
    idx = min(len(values) - 1, int(len(values) * p))
    return round(values[idx], 1)


# 按统一格式打印一组延迟的分位统计,方便各阶段结果横向对比。
def report(name: str, values: list[float]) -> None:
    print(
        f"  {name:<24} P50={percentile(values, 0.5):>8.1f}ms  "
        f"P95={percentile(values, 0.95):>8.1f}ms  P99={percentile(values, 0.99):>8.1f}ms"
    )


# 三阶段设计:先测无 AI 参与的纯接口延迟(排除检索/生成的干扰),
# 再测 SSE 问答的流式体验,最后用重复提问量化语义缓存的提速效果。
async def main() -> None:
    parser = argparse.ArgumentParser(description="LangChainRAG 性能压测")
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--concurrency", type=int, default=3, help="并发问答数")
    parser.add_argument("--questions", type=int, default=10, help="总问题数")
    parser.add_argument("--health", action="store_true", help="仅测健康检查与接口延迟")
    args = parser.parse_args()

    # 压测前先验证服务可用:登录失败会在此直接抛错,避免后面的请求全部白跑。
    token = await login(args.base)
    headers = {"Authorization": f"Bearer {token}"}
    print(f"压测目标: {args.base}  并发: {args.concurrency}  问题数: {args.questions}\n")

    async with httpx.AsyncClient(base_url=args.base, headers=headers, timeout=120) as client:
        # 1. 基础接口延迟
        api_lat = []
        # 选 GET /api/conversations:接口轻量、无 AI 参与,能反映服务本身的水位。
        # 连续打 20 次取分布:单次测量受网络抖动影响大,样本越多分位值越可信。
        for _ in range(20):
            el, resp = await measure_api(client, "GET", "/api/conversations")
            api_lat.append(el)
            # 断言接口可用:基础接口都失败时,后续问答压测没有意义。
            assert resp.status_code == 200
        print("[接口] GET /api/conversations")
        report("接口延迟", api_lat)

        # 2. 问答并发压测(首 token 延迟)
        # Semaphore 限制同时进行的请求数,模拟 N 个用户同时在线的场景。
        sem = asyncio.Semaphore(args.concurrency)
        # 首 token 数组与回答数组按下标一一对应,便于事后核对单个请求。
        first_tokens: list[float] = []
        answers: list[str] = []
        ok_count = 0

        async def worker(i: int):
            nonlocal ok_count
            # 问题轮流取用,避免所有并发请求同时打到同一个缓存键。
            q = QUESTIONS[i % len(QUESTIONS)]
            async with sem:
                try:
                    # 单次问答走完整 RAG 链路:检索 → 重排 → 模型生成,耗时主要在后两者。
                    ft, text = await chat_once(client, None, q)
                    first_tokens.append(ft)
                    answers.append(text)
                    if text.strip() and len(text) > 20:
                        # 回答长度 > 20 字视为成功:过短的响应大概率是错误/空回答。
                        ok_count += 1
                    print(f"  [{i+1}/{args.questions}] 首 token {ft:.0f}ms  长度 {len(text)}")
                except Exception as e:  # noqa: BLE001
                    # 单个请求失败不中断压测,记录后继续,最后看整体成功率。
                    print(f"  [{i+1}/{args.questions}] 失败: {e}")

        await asyncio.gather(*[worker(i) for i in range(args.questions)])
        print("\n[问答] SSE 流式(含检索+重排+生成)")
        # 首 token 延迟涵盖检索+重排+生成首字,是端到端流式体验的直观指标。
        report("首 token 延迟", first_tokens)
        # 成功率低于预期,说明并发下服务出现了超时或错误。
        print(f"  成功回答: {ok_count}/{args.questions}")

        # 3. 缓存命中对比(重复提问同一问题)
        # 只有前面有成功样本时才有对比意义:完全失败时跳过缓存对比。
        if first_tokens:
            q = QUESTIONS[0]
            # 两次问同一个问题:第一次走完整 RAG 链路,第二次应命中语义缓存。
            ft1, _ = await chat_once(client, None, q)
            ft2, _ = await chat_once(client, None, q)
            print("\n[缓存] 重复问题对比")
            # 提速比 =(首次 - 二次)/ 首次:值越高说明缓存收益越明显。
            print(f"  首次: {ft1:.0f}ms   二次(应命中缓存): {ft2:.0f}ms   (提速 {(ft1 - ft2) / max(ft1, 1) * 100:.0f}%)")


if __name__ == "__main__":
    # 模块级守卫:作为脚本直接执行;被 import 时不会自动跑压测。
    asyncio.run(main())
