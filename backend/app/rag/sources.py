"""引用来源结构与 snippet 提取。"""
# 引用契约是"翻译层":同一批证据,既要变成提示词里的编号 [n],也要变成前端弹层的引用列表
import logging

logger = logging.getLogger(__name__)

SNIPPET_LIMIT = 150  # 引用弹层展示的原文片段长度;够用户判断来源,又不撑爆弹层


# 生成引用摘要:换行压成空格、截断加省略号——弹层空间有限,超长原文只保留头部
def make_snippet(content: str, limit: int = SNIPPET_LIMIT) -> str:
    text = content.replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


# 把重排后的候选转成引用契约结构(与 messages.sources JSON 一致),供前端引用弹层渲染
def make_sources(ranked_chunks: list[dict]) -> list[dict]:
    """把重排后的候选转成引用契约结构(与 messages.sources JSON 一致)。

    ranked_chunks: [{payload, score}],顺序即引用编号顺序(index 从 1 开始)。
    """
    sources = []
    # 入参顺序即展示顺序:重排后的优先序保留,不在此处二次排序
    for i, item in enumerate(ranked_chunks, start=1):
        payload = item.get("payload") or {}
        # 字段缺失给空值兜底:前端渲染无需判空,未命中数据也能正常展示
        sources.append(
            {
                # index 从 1 开始:与提示词里的编号 [n] 对齐,模型引用和前端弹层才能对上
                "index": i,
                "doc_id": payload.get("doc_id", ""),
                # doc_title 是用户看到的来源名(入库时的文件名),不是内部标识
                "doc_title": payload.get("doc_title", ""),
                # page/section 可能为空(pdf 无页码、txt 无章节),原样透传由前端按需展示
                "page": payload.get("page"),
                "section": payload.get("section"),
                # chunk_content 与 text 二选一:兼容入库 payload 与测试数据两种形状
                "snippet": make_snippet(payload.get("chunk_content") or payload.get("text") or ""),
                # 分数保留 4 位:展示相关度排序用,过长的小数无意义
                "score": round(float(item.get("score", 0.0)), 4),
            }
        )
    return sources
