"""SSE 传输层探针:最小化复现"meta 帧后流中断"问题。

对比实验:EventSourceResponse yield dict vs 裸 StreamingResponse。
"""
import asyncio
import json

import httpx
import uvicorn
from fastapi import FastAPI
from sse_starlette.sse import EventSourceResponse
from starlette.responses import StreamingResponse

# 探针服务:独立于主应用,只暴露 3 个 SSE 端点做传输层对比实验。
probe = FastAPI()


# 端点 1:EventSourceResponse + yield dict 对象,
# 这是 sse-starlette 推荐的"结构化写法",由库负责把 dict 序列化成 SSE 帧。
@probe.get("/sse-dict")
async def sse_dict():
    async def gen():
        for i in range(5):
            # 每 0.5 秒推一帧 delta 事件,模拟流式生成的推送节奏。
            yield {"event": "delta", "data": json.dumps({"text": f"第{i}帧"})}
            await asyncio.sleep(0.5)

    # EventSourceResponse 会包装生成器,把 dict 帧序列化为 "event: X\ndata: {...}\n\n" 格式。
    return EventSourceResponse(gen())


# 端点 2:EventSourceResponse + 手工拼好的字符串帧,
# 验证"库内部二次处理字符串"是否与 dict 走同一条序列化路径。
@probe.get("/sse-str")
async def sse_str():
    async def gen():
        for i in range(5):
            yield f"event: delta\ndata: {json.dumps({'text': f'第{i}帧'})}\n\n"
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen())


# 端点 3:完全绕开 sse-starlette,用裸 StreamingResponse 手写帧,
# 对照组的意义是确认"问题出在库的封装层,还是我们自己拼帧的格式"。
@probe.get("/raw")
async def raw_stream():
    async def gen():
        for i in range(5):
            yield f"event: delta\ndata: {json.dumps({'text': f'第{i}帧'})}\n\n"
            await asyncio.sleep(0.5)

    # media_type 必须为 text/event-stream:浏览器 EventSource 只认这个 MIME 才当 SSE 解析。
    return StreamingResponse(gen(), media_type="text/event-stream")


# 客户端:逐个访问三个端点,把收到的原始字节打印出来对比帧格式差异。
async def test() -> None:
    print("=" * 50)
    # 对比只关心"收到什么",不校验状态码:帧格式差异正是本次实验的目标。
    # 逐个访问而非并发:输出顺序清晰,便于对照三个端点的帧差异。
    for path in ("/sse-dict", "/sse-str", "/raw"):
        print(f"\n[{path}]")
        # 30s 超时兜底:5 帧 × 0.5s ≈ 2.5s 即可收完,余量充足。
        async with httpx.AsyncClient(timeout=30) as c:
            async with c.stream("GET", f"http://127.0.0.1:9911{path}") as resp:
                body = ""
                # 逐块累积原始字节:探针要看"字节层面"的完整帧,不能只取文本。
                async for chunk in resp.aiter_bytes():
                    body += chunk.decode("utf-8", errors="ignore")
            # repr 会保留 \n 等转义符,肉眼可直接看出帧分隔符是否完整。
            print("收到:", repr(body))


if __name__ == "__main__":
    import threading

    # 探针服务跑在独立线程里:主线程负责发请求收结果,两者互不阻塞。
    server = uvicorn.Server(uvicorn.Config(probe, host="127.0.0.1", port=9911, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    # daemon=True:主线程退出时守护线程自动终止,不会留下僵尸线程。
    thread.start()
    import time

    # 等 uvicorn 完成端口监听再发请求,否则会连接被拒。
    time.sleep(2)
    asyncio.run(test())
    # 测试完成后通知 uvicorn 优雅退出,避免脚本挂住不结束。
    server.should_exit = True
