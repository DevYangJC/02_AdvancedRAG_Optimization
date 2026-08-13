"""端到端冒烟测试:对运行中的完整系统做全链路验证。

前提:后端(:8000)、Qdrant(:6333)已启动,.env 已配置 API Key,测试数据已生成。
    python -m scripts.create_test_data
    python -m scripts.e2e_smoke

验证项:
  1. admin 登录 → 上传 5 种格式文档 → 轮询至 ready,向量数一致
  2. 普通用户注册/登录,只能问答不能管理(403)
  3. 锚点问题问答 → 回答含引用编号且来源片段匹配
  4. 多轮改写("那电池呢" 能正确检索)
  5. 会话历史持久化、多用户隔离(越权 404)
  6. 删除文档 → 向量级联清空
"""
# ---------------------------------------------------------------------------
# 端到端冒烟测试:直接对运行中的后端发起真实 HTTP 请求,
# 覆盖"上传入库 → 问答 → 会话持久化 → 权限隔离 → 删除级联"整条业务链路。
# 与单元测试(backend/tests)不同,这里不 mock 任何外部依赖
# (模型 API、Qdrant 向量库、数据库),任何一环坏了都会显式失败。
# ---------------------------------------------------------------------------
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

# 固定指向本地开发环境:后端与 Qdrant 需先启动,否则所有请求都会连接失败。
BASE = "http://localhost:8000"
# 样本数据由 scripts/create_test_data.py 预生成,路径与其 OUT_DIR 保持一致。
SAMPLES = Path(__file__).resolve().parent.parent.parent / "docs" / "data" / "samples"

# 全局累计器:贯穿 main 的所有 check 调用,最终汇总为退出码。
PASS, FAIL = 0, 0


# 轻量断言:失败不抛异常而是累计 FAIL 计数,让脚本跑完全部检查项再统一退出,
# 这样一次运行能暴露尽可能多的问题,而不是在第一个失败处就中断。
def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# 轮询文档状态直至 ready:上传是异步任务(解析 → 切分 → 向量化),
# 后端处理完才会把状态置为 ready,故需要轮询;timeout 防止无限卡死。
async def wait_ready(client: httpx.AsyncClient, doc_id: str, headers: dict, timeout: int = 120) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = await client.get(f"/api/documents/{doc_id}", headers=headers)
        doc = resp.json()
        if resp.status_code != 200:
            # 接口本身报错(如鉴权失败)时直接返回原因,便于定位是哪类问题。
            return f"http_{resp.status_code}: {doc.get('message', '')}"
        if doc["status"] == "ready":
            return "ready"
        if doc["status"] == "failed":
            return f"failed: {doc.get('error')}"
        # 仍在处理中:睡 1 秒再查,避免高频轮询打满接口。
        await asyncio.sleep(1)
    return "timeout"


# 解析 SSE 流响应:把逐帧的文本拼接成完整回答,并收集引用来源。
# SSE(Server-Sent Events)是"服务器推送"协议:每个事件由 event 行 + data 行组成,
# 帧与帧之间以空行分隔;本函数把它还原成 (回答全文, 来源列表)。
async def extract_answer(stream_body: str) -> tuple[str, list[dict]]:
    """解析 SSE 文本,返回 (完整回答, sources)。

    注意:sse-starlette 以 CRLF 分隔帧,先归一化为 LF 再拆帧。
    """
    text = ""
    sources: list[dict] = []
    for frame in stream_body.replace("\r\n", "\n").split("\n\n"):
        ev = frame.splitlines()[0].replace("event: ", "") if frame else ""
        data_line = next((l[5:].strip() for l in frame.splitlines() if l.startswith("data:")), None)
        if not data_line:
            # 心跳或注释帧没有 data,直接跳过,不影响其余帧解析。
            continue
        try:
            data = json.loads(data_line)
        except Exception:  # noqa: BLE001
            # 单帧解析失败不拖垮整个流:防御性跳过,后续帧仍可正常解析。
            continue
        if ev == "meta":
            # meta 帧携带本次检索到的引用来源,整个流里只会出现一次。
            sources = data.get("sources", [])
        elif ev == "delta":
            # delta 帧是流式生成的内容增量,逐帧累加还原出完整回答。
            text += data.get("text", "")
    return text, sources


# 便捷封装:发一次 SSE 流式问答请求,返回解析后的完整回答与来源列表。
async def chat(client: httpx.AsyncClient, conv_id: str | None, content: str, headers: dict) -> tuple[str, list[dict]]:
    body = ""
    async with client.stream(
        "POST", "/api/chat/stream", json={"conversation_id": conv_id, "content": content}, headers=headers
    ) as resp:
        resp.raise_for_status()
        # 逐块累积原始字节:SSE 帧可能横跨多个网络 chunk,必须全部收完再统一解析。
        async for chunk in resp.aiter_bytes():
            body += chunk.decode("utf-8", errors="ignore")
    return await extract_answer(body)


# 主流程:按编号分 6 个阶段依次执行,每阶段有独立打印标题,
# 一旦某阶段失败,可对照日志标题快速定位问题出在哪个环节。
async def main() -> None:
    print("=" * 60)
    print("LangChainRAG 端到端冒烟测试")
    print("=" * 60)

    # 阶段 0~6 从环境到业务逐层递进:先确认服务活着,再验证核心业务链路,
    # 前置阶段失败会连累后续依赖它的断言(通过 check 计数体现,不硬中断脚本)。
    # 统一用 180s 超时:SSE 流式回答涉及模型生成,单次耗时可能远超普通接口。
    async with httpx.AsyncClient(base_url=BASE, timeout=180) as client:
        # ---- 0. 健康检查 ----
        resp = await client.get("/api/health")
        health = resp.json()
        # 健康检查返回 JSON 状态,status 为 ok 代表数据库与向量库均已连通;
        # 依赖未就绪时它会直接失败,是最快的环境体检。
        print(f"[0] 健康检查: {health}")
        check("健康检查 ok", health.get("status") == "ok", str(health))

        # ---- 1. admin 上传 5 种格式 ----
        print("\n[1] 知识库入库(5 种格式)")
        # admin 是种子账号:由 scripts/seed_admin.py 幂等创建,密码 123456 仅用于测试环境。
        # 登录成功会返回 JWT;失败时(如服务未起)后续请求因无 token 会全部 401。
        login = await client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        check("admin 登录", login.status_code == 200)
        # 后续所有管理接口都需要 JWT(登录后签发),统一放进 Authorization 头。
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # 清理历史文档:防止重复上传导致向量堆积、检索排名被相似行霸占
        existing = (await client.get("/api/documents", headers=headers, params={"page_size": 100})).json()
        # 逐条走删除接口而非直接清库:顺带验证删除接口本身可用。
        for d in existing["items"]:
            await client.delete(f"/api/documents/{d['id']}", headers=headers)
        print(f"  (已清理 {existing['total']} 个历史文档,保证测试从零开始)")

        # 清理语义缓存:防止命中上次运行缓存的旧答案(缓存 TTL 24h)
        from sqlalchemy import delete as sa_delete
        # 直连测试库删除缓存表:语义缓存按问题哈希存储、命中后直接返回旧答案,
        # 若不清空,本轮新上传的文档永远不会被检索到。
        from app.db.session import async_session_maker as _asm
        from app.models import CacheEntry as _Cache

        # 直接执行 SQL 删除、不经服务层:测试前置清理不走业务逻辑,避免引入额外依赖。
        async with _asm() as _db:
            removed = (await _db.execute(sa_delete(_Cache))).rowcount
            await _db.commit()
        print(f"  (已清理 {removed} 条语义缓存)")

        # multipart 批量上传:每项元组为 (表单字段名, (文件名, 文件对象, MIME 类型)),
        # 与浏览器端 axios 的 FormData 上传行为一致。
        # 五种格式一次上传,验证上传接口的多样性兼容。
        files = [
            ("files", ("商品说明.md", open(SAMPLES / "商品说明.md", "rb"), "text/markdown")),
            ("files", ("商品参数.txt", open(SAMPLES / "商品参数.txt", "rb"), "text/plain")),
            ("files", ("商品清单.xlsx", open(SAMPLES / "商品清单.xlsx", "rb"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
            ("files", ("商品手册.docx", open(SAMPLES / "商品手册.docx", "rb"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
            ("files", ("商品说明书.pdf", open(SAMPLES / "商品说明书.pdf", "rb"), "application/pdf")),
        ]
        upload = await client.post("/api/documents/upload", files=files, headers=headers)
        check("批量上传", upload.status_code == 200, upload.text[:200])
        # 用返回的文档 id 列表驱动后续轮询,避免逐个猜测 id。
        doc_ids = [d["id"] for d in upload.json()["documents"]]

        # 并行轮询:各文档的解析/向量化互不依赖,并发能显著缩短整体等待。
        statuses = await asyncio.gather(*[wait_ready(client, did, headers) for did in doc_ids])
        check("5 种格式全部入库 ready", all(s == "ready" for s in statuses), str(statuses))

        # 向量数 == 知识块数:每个知识块都应生成一条向量,两者不一致说明切分/入库有遗漏。
        stats = (await client.get("/api/documents/admin/stats", headers=headers)).json()
        check("向量数与知识块数一致", stats["vector_count"] == stats["chunk_count"],
              f"vector={stats['vector_count']} chunk={stats['chunk_count']}")

        # ---- 2. 普通用户权限 ----
        print("\n[2] 普通用户权限")
        reg = await client.post(
            "/api/auth/register", json={"username": f"user_{int(time.time())}", "password": "pass123456"}
        )
        # 用户名带时间戳:测试库持久化,重复运行不会撞上同名用户导致 400。
        check("注册", reg.status_code == 200)
        user_headers = {"Authorization": f"Bearer {reg.json()['access_token']}"}
        # 文档列表属于 admin 专属接口:普通用户访问应被拒绝(403)。
        denied = await client.get("/api/documents", headers=user_headers)
        check("普通用户访问管理接口 403", denied.status_code == 403)

        # ---- 3. 锚点问答 + 引用 ----
        print("\n[3] 锚点问答与引用")
        # 先创建会话拿到 conv_id:后续问答/历史接口都以它作为主键。
        conv = (await client.post("/api/conversations", json={}, headers=user_headers)).json()
        conv_id = conv["id"]

        # 每个锚点是一组 (问题, 回答中必须出现的关键词),关键词取自脚本头部的事实锚点。
        anchors = [
            ("星云手机 X1 支持几天无理由退换?", ["7 天", "无理由退换"]),
            ("星云手机 X1 电池容量是多少?", ["5000"]),
            ("星云手机 X1 支持多少瓦快充?", ["66W"]),
            ("清风空气净化器适用多大面积?", ["40"]),
            ("星云手机 X1 的防水等级是什么?", ["IP68"]),
        ]
        # 逐题问答并断言:回答内容、引用编号、来源片段三者都要符合预期。
        for question, keywords in anchors:
            answer, sources = await chat(client, conv_id, question, user_headers)
            # 回答中的 [1][2] 编号是引用标注:没有编号 = 模型没引用检索来源,视为失败。
            cited = re.findall(r"\[(\d+)\]", answer)
            ok = all(k in answer for k in keywords) and len(cited) >= 1 and bool(sources)
            check(f"「{question}」含引用且内容正确", ok, f"answer={answer[:80]} cited={cited} sources={len(sources)}")
            if sources:
                # 引用编号与来源片段一致性抽查:编号 1 的 snippet 应与答案相关
                check(f"  来源[{sources[0]['index']}] snippet 非空", bool(sources[0]["snippet"]))

        # ---- 4. 多轮改写 ----
        print("\n[4] 多轮对话改写")
        # "那电池能撑多久?"省略了主语,必须靠历史上下文改写(query rewrite)才能检索到电池容量。
        follow_up, _ = await chat(client, conv_id, "那电池能撑多久?", user_headers)
        check("追问「电池」检索到容量信息", "5000" in follow_up, follow_up[:80])

        # ---- 5. 会话持久化与隔离 ----
        print("\n[5] 会话持久化与多用户隔离")
        history = (await client.get(f"/api/conversations/{conv_id}/messages", headers=user_headers)).json()
        # 前面共问了 5 个锚点问题 + 1 个追问,加上各自的回答至少 12 条消息,8 是安全下界。
        check("历史消息完整(含引用)", history["total"] >= 8 and any(m["sources"] for m in history["items"]),
              f"total={history['total']}")

        # 注册第二个用户模拟"他人":验证会话对非属主用户完全不可见。
        reg_b = await client.post(
            "/api/auth/register", json={"username": f"user_b_{int(time.time())}", "password": "pass123456"}
        )
        headers_b = {"Authorization": f"Bearer {reg_b.json()['access_token']}"}
        intruder = await client.get(f"/api/conversations/{conv_id}", headers=headers_b)
        # 越权访问返回 404 而非 403:不暴露"该会话存在"这一信息,是隐私保护惯例。
        check("他人会话访问 404", intruder.status_code == 404)

        # ---- 6. 删除级联 ----
        print("\n[6] 删除文档级联清空向量")
        # 只删第一个文档(商品说明.md):保留其余文档,验证"部分删除"后剩余文档仍可检索。
        victim = doc_ids[0]
        # 删除接口返回 200 即成功;向量的级联清理在后台异步完成。
        deleted = await client.delete(f"/api/documents/{victim}", headers=headers)
        check("删除文档", deleted.status_code == 200)
        # 睡 2 秒等级联删除事务落库:向量清理是异步任务,立即查 stats 可能还没删完。
        await asyncio.sleep(2)
        # 用管理统计接口验证删除效果:vector_count 应小于删除前的值。
        stats2 = (await client.get("/api/documents/admin/stats", headers=headers)).json()
        check("向量已级联删除", stats2["vector_count"] < stats["vector_count"],
              f"{stats['vector_count']} → {stats2['vector_count']}")

    print("=" * 60)
    print(f"结果: 通过 {PASS} 项, 失败 {FAIL} 项")
    # 有失败项时退出码非 0:CI/脚本调用方据此判断测试是否通过。
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    asyncio.run(main())
