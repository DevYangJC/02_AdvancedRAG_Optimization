"""问答编排核心:缓存 → 改写 → 检索 → 重排 → 引用编号 → LCEL 流式 → 落库。

SSE 事件协议(与前端 useSSE.ts 契约):
  meta:  {conversation_id, message_id, sources:[...]}
  delta: {text}
  done:  {message_id, full_text, sources}
  error: {code, message}

断流/异常处理:落已生成部分并置 status=error,前端可重试,答案不丢失。
"""
# RAG(检索增强生成)主链路:先检索知识库证据,再让模型基于证据作答,回答有据可查、可引用
# SSE 事件产出顺序固定为 meta → delta… → done/error,前端 useSSE.ts 依赖该顺序渲染
# 任何异常路径都保证"已生成内容落库 + 明确错误事件",不让前端卡死在生成中
# ConflictError 等业务错误由 API 层转 HTTP 状态码;本文件只处理流式会话内的错误
import asyncio
import json
import logging
from datetime import datetime

from sqlalchemy import select

from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, ServiceUnavailableError
from app.db.session import async_session_maker
from app.models import Conversation, Message, User
from app.rag import reranker
from app.rag.chain import build_chat_pipeline
from app.rag.prompt import build_context, build_user_prompt
from app.rag.retriever import retrieve
from app.rag.rewrite import rewrite_query
from app.rag.sources import make_sources
from app.schemas.conversation import ChatRequest
from app.services import cache_service, conversation_service, llm_service

logger = logging.getLogger(__name__)

# 进行中的会话(防止同一会话并发提问)
# 为什么用内存集合而非数据库锁:同会话并发提问是低概率事件,内存判重开销最小
# 注意:多进程部署时该集合按进程隔离,跨进程并发需数据库层兜底(当前单进程部署可接受)
_inflight: set[str] = set()

# 重排候选上限:检索 top-K 中截取前 N 个送重排(控制 API 成本与延迟)
_RERANK_CANDIDATE_LIMIT = 50
_RERANK_DOC_TRUNCATE = 300
# 重排请求量 = 目标条数 × 2,去重后仍能保证数量(相似内容霸占候选时的多样性兜底)
_RERANK_OVERFETCH = 2
# 检索候选阶段:每个文档最多进入重排的条数(文档多样性采样,防相似行霸占候选)
_MAX_PER_DOC = 8


# 并发保护:同一会话同时只允许一个生成任务,防止两路回答互相覆盖该会话的消息记录
def _check_inflight(conv_id: str) -> None:
    if conv_id in _inflight:
        raise ConflictError("该会话正在生成回答,请稍候再试", "conversation_busy")
    _inflight.add(conv_id)


# 收尾清理:无论成败都要释放,否则该会话会被永久锁定,再也无法提问
def _release_inflight(conv_id: str) -> None:
    _inflight.discard(conv_id)


async def _get_history(db, conv_id: str, limit: int | None = None) -> list[dict]:
    """取会话最近 N 条消息(不含未完成的)。"""
    # 只取 completed 状态:进行中/中断的半截消息不能作为上下文,避免把残句喂给模型
    # 窗口上限来自配置:历史过长会稀释当前问题的注意力,同时推高 token 成本
    limit = limit or settings.history_messages
    rows = (
        await db.execute(
            select(Message)
            .where(Message.conversation_id == conv_id, Message.status == "completed")
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    # 倒序取"最新 N 条"再反转:SQL 只能降序取尾,业务需要按时间正序交给模型
    # 只保留 {role, content}:token 数等内部字段不进提示词,防止泄露内部信息
    return [{"role": m.role, "content": m.content} for m in reversed(rows)]


def _diverse_candidates(hits: list[dict]) -> list[dict]:
    """文档多样性采样:每文档最多 _MAX_PER_DOC 条,按相关性顺序轮询交织。

    解决场景:商品清单类文档的相似行(型号/颜色略有差异)embedding 高度相似,
    会霸占检索结果前列,把其他文档的关键段落挤出重排候选。
    """
    # 按 doc_id 分桶,每桶最多 _MAX_PER_DOC 条,先到先得
    # 输入 hits 已按相似度降序,桶内顺序即相关度顺序;是否更优由后续 rerank 裁决
    per_doc: dict[str, list[dict]] = {}
    for h in hits:
        doc_id = h["payload"].get("doc_id", "")
        bucket = per_doc.setdefault(doc_id, [])
        if len(bucket) < _MAX_PER_DOC:
            bucket.append(h)
    candidates: list[dict] = []
    # 轮询交织:每个桶各取一条再轮到下一个,直到取满上限或全部耗尽
    while candidates.__len__() < _RERANK_CANDIDATE_LIMIT:
        progressed = False
        for doc_id in list(per_doc):
            bucket = per_doc[doc_id]
            if bucket:
                candidates.append(bucket.pop(0))
                progressed = True
                if candidates.__len__() >= _RERANK_CANDIDATE_LIMIT:
                    break
        # 没有任何桶还有剩余说明已取尽,提前结束避免死循环
        if not progressed:
            break
    return candidates


async def _retrieve_rank(query: str, doc_ids: list[str] | None) -> list[dict]:
    """检索 → 重排 → 返回按候选顺序排列的 chunks(payload 内带 chunk_content)。"""
    # 向量检索(召回)负责"宽进":用 embedding 余弦相似度找回相关候选,保证不漏
    hits = await retrieve(query, settings.retrieve_dense_top_k, doc_ids)
    if not hits:
        # 检索为空直接返回:省去一次无意义的重排 API 调用
        return []
    candidates = _diverse_candidates(hits)
    # 截断到 300 字符再送重排:重排按 token 计费,超长文本的边际收益递减
    docs = [(c["payload"].get("chunk_content") or "")[:_RERANK_DOC_TRUNCATE] for c in candidates]
    # 重排取 2 倍候选,给去重留余量(相似内容霸占候选时的多样性保障)
    ranked = await reranker.rerank(query, docs, top_n=settings.rerank_top_n * _RERANK_OVERFETCH)
    # 重排(精排)返回 (index, score),用 index 反查原候选——向量相似度对语义的误判在此纠正
    ordered = [candidates[idx] for idx, _ in ranked]
    # 分数回填:make_sources 用它展示"相关度",也可用于后续解释答案来源
    for item, (_, score) in zip(ordered, ranked):
        item["score"] = score

    # 内容去重:相同文本只保留分数最高的一条,保证上下文多样性
    # (典型场景:xlsx 同一商品多行高度相似,会霸占全部候选导致关键段落被挤掉)
    # 去重后直接截断到目标条数,与 rerank_top_n 对齐,不多取也不少取
    seen: set[str] = set()
    deduped: list[dict] = []
    for item in ordered:
        # 无文本可比的记录用 doc_id 兜底,仍能触发去重,避免同一文档重复段入选
        key = item["payload"].get("chunk_content") or item["payload"].get("doc_id", "")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= settings.rerank_top_n:
            break
    return deduped


# 问答主流程生成器:db=请求会话、user=当前用户、req=提问请求;逐个 yield SSE 事件字典
async def stream_chat(db, user: User, req: ChatRequest):
    """问答流式生成器:yield {type, data} 事件字典。"""

    # ---------- 1. 会话校验/创建 ----------
    # 归属校验与查询一体完成:非本人会话一律 404,不暴露会话是否存在
    # 带 conversation_id 进入多轮,不带则新建会话(截取问题作初始标题)
    conv = None
    if req.conversation_id:
        conv = await conversation_service.get_owned_conversation(db, user.id, req.conversation_id)
    else:
        # 新会话标题取问题前 20 字:先给侧边栏可读的初始名,首答后再由 LLM 精修
        conv = await conversation_service.create_conversation(db, user, req.content[:20])
    conv_id = conv.id
    # conv_id 是后续所有环节(写消息、检索过滤、落库、标题)的锚点
    # 排他锁生效:后续所有分支(含缓存命中提前 return)由 finally 统一释放,不会锁死会话
    _check_inflight(conv_id)

    # 是否首条消息(决定是否生成标题):该会话此前没有任何消息记录即为首条
    # 用 limit(1) 而非 count(*):命中即止,大会话下查询更快
    msg_count = (
        await db.execute(select(Message).where(Message.conversation_id == conv_id).limit(1))
    ).first()

    # ---------- 2. 落用户消息(独立会话) ----------
    # 独立写会话:请求会话可能在中途超时/取消,用户消息必须先落库,保证"提问不丢"
    async with async_session_maker() as write_db:
        # 用户消息天然是完成态:内容无需生成,直接标 completed
        user_msg = Message(conversation_id=conv_id, role="user", content=req.content, status="completed")
        write_db.add(user_msg)
        # 提问即刷新活跃时间:侧边栏按 updated_at 倒序,刚提问的会话应浮到顶部
        conv_owner = await write_db.get(Conversation, conv_id)
        # guard:会话刚校验过理论上必在,防御性检查避免并发删除场景报错
        if conv_owner:
            conv_owner.updated_at = datetime.now()
        await write_db.commit()
        # commit 后 id 才生成,先提交再取;后续事件都携带该 id 供前端定位消息
        user_msg_id = user_msg.id

    try:
        # ---------- 3. 历史与语义缓存 ----------
        # 历史先于改写加载:改写需要完整的多轮上下文,而非只看当前一句
        # 同一份历史在改写与生成两处复用,避免重复查询数据库
        history = await _get_history(db, conv_id)
        # 缓存 key 只基于规范化问题,与多轮历史无关——多轮追问通常不命中,属预期行为
        cached = await cache_service.get_cached(db, req.content)
        if cached is not None:
            # 缓存命中即整体返回:改写/检索/重排/生成全部跳过,这是缓存收益最大的路径
            sources = cached.sources or []
            yield {
                "type": "meta",
                "data": {"conversation_id": conv_id, "message_id": user_msg_id, "sources": sources},
            }
            # 命中时先 meta 后整段 delta:前端直接渲染完整答案,不再"逐字打字"
            yield {"type": "delta", "data": {"text": cached.answer}}
            yield {"type": "done", "data": {"message_id": user_msg_id, "full_text": cached.answer, "sources": sources}}
            # 缓存命中同样落库一条 assistant 消息,保证消息列表与真实问答记录一致
            await _save_assistant(conv_id, user_msg_id, cached.answer, sources, cached=True)
            return

        # ---------- 4. 改写 → 检索 → 重排 → 引用 ----------
        # 改写把多轮口语补全为独立检索问题(如"它多少钱"→"该商品多少钱"),是检索质量的关键前置
        # 改写失败内部已回退原问题,这里无需 try,不会阻塞主流程
        question = await rewrite_query(history, req.content)
        # doc_ids 过滤由前端传入(如"仅看某文档"),过滤在向量库层完成,比取回后再滤更省
        ranked = await _retrieve_rank(question, req.doc_ids)
        # make_sources 生成前端引用契约,build_context 生成模型可见的证据文本
        sources = make_sources(ranked)
        context = build_context(ranked)

        # 引用与上下文共用同一顺序:提示词里的编号 [n] 才与前端引用弹层一一对应
        yield {
            "type": "meta",
            "data": {"conversation_id": conv_id, "message_id": user_msg_id, "sources": sources},
        }

        # ---------- 5. LCEL 流式生成 ----------
        # full_text 累计完整答案(供 done/error 事件与落库),error 记录生成期异常
        full_text = ""
        error: Exception | None = None
        try:
            # LCEL(LangChain 表达式语言):prompt|model 管道,链对象可复用、天然支持流式
            chain = build_chat_pipeline()
            # 信号量保护:同一时刻最多 llm_max_concurrency 路生成,防 DashScope 限流雪崩
            async with llm_service.get_semaphore():
                # 链输入三要素:历史(多轮理解)、上下文(知识库证据)、原始问题(而非改写后的)
                async for chunk in chain.astream(
                    {
                        "history": [(h["role"], h["content"]) for h in history],
                        "context": context,
                        "question": req.content,
                    }
                ):
                    # hasattr 兼容不同模型的返回对象:个别实现无 .content,退化为字符串
                    piece = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if piece:
                        full_text += piece
                        # 逐块转发 delta:前端边收边渲染,首字延迟即首字体验
                        yield {"type": "delta", "data": {"text": piece}}
        except asyncio.CancelledError:
            # 客户端断开场景:保存已生成部分后原样抛出取消,不吞信号
            # shield 防取消扩散:即使外层任务被取消,落库协程也要完整执行
            await asyncio.shield(_save_assistant(conv_id, user_msg_id, full_text, sources, status="error"))
            raise
        except Exception as e:  # noqa: BLE001
            # 生成器中断(流断/服务端报错):记录错误后继续走统一收尾,不发 done
            error = e
            logger.error("生成中断: %s", e)

        if error is None:
            # 成功收尾:落库 + 写缓存 + 发 done;缓存只存完整答案,失败/中断内容不缓存
            # 写缓存放在落库之后、done 之前:前端收到 done 时数据库里已有完整记录
            await _save_assistant(conv_id, user_msg_id, full_text, sources)
            await cache_service.set_cached(db, req.content, full_text, sources, settings.llm_model)
            yield {"type": "done", "data": {"message_id": user_msg_id, "full_text": full_text, "sources": sources}}
        else:
            # 断流/异常:保存已生成部分,并附 partial 供前端提示"已保存部分回答,可重试"
            await _save_assistant(conv_id, user_msg_id, full_text, sources, status="error")
            yield {
                "type": "error",
                "data": {
                    "code": "STREAM_INTERRUPTED",
                    "message": f"回答生成中断(已保存已生成内容): {error}",
                    "partial": full_text,
                },
            }
    except ServiceUnavailableError as e:
        # 改写/检索/重排等环节的明确业务错误(如未配置 API Key):直接透出错误码,不吞成内部错误
        await _save_assistant(conv_id, user_msg_id, "", None, status="error")
        yield {"type": "error", "data": {"code": e.code, "message": e.message}}
    except Exception as e:  # noqa: BLE001
        # 兜底:未知异常记录堆栈,落 error 消息,统一对外为 INTERNAL_ERROR
        logger.exception("问答异常")
        await _save_assistant(conv_id, user_msg_id, "", None, status="error")
        yield {"type": "error", "data": {"code": "INTERNAL_ERROR", "message": f"服务器内部错误: {e}"}}
    finally:
        # 释放排他锁:此后该会话可以再次提问
        _release_inflight(conv_id)

    # ---------- 6. 首条消息异步生成标题 ----------
    # 标题生成放最后且不阻塞回答流;失败时内部已回退为截断的问题文本
    if msg_count is None:
        await conversation_service.generate_title(db, conv_id, req.content)


async def _save_assistant(
    conv_id: str,
    user_msg_id: str,
    content: str,
    sources: list[dict] | None,
    status: str = "completed",
    cached: bool = False,
# 参数:cached=True 表示消息来自缓存命中(仅用于日志区分);status 控制消息显示形态
) -> str:
    """落 assistant 消息并刷新会话活跃时间;返回消息 id。"""
    # 使用独立会话写库:流式生成期间主请求会话可能已超时/取消,写库不能跟着丢
    async with async_session_maker() as db:
        msg = Message(
            conversation_id=conv_id,
            role="assistant",
            content=content or "(未生成内容)",  # 空内容占位:保证前端不渲染空白气泡
            sources=sources,
            status=status,
            # token_count 粗略估算(1 汉字≈2 字符):仅服务管理统计,精确值需调 tokenizer,不值当
            token_count=len(content) // 2,
        )
        db.add(msg)
        # 回答落库同样刷新活跃时间,保持侧边栏排序与最后活动一致
        conv = await db.get(Conversation, conv_id)
        if conv:
            conv.updated_at = datetime.now()
        await db.commit()
        if cached:
            logger.info("缓存命中已落库 conv=%s", conv_id)
        # 返回的 id 随 done 事件回传,前端用它把答案气泡关联到对应提问
        return msg.id
