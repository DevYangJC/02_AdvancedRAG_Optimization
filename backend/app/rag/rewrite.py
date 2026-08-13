"""多轮对话改写:把"当前问题 + 历史"压缩为独立的自包含检索问题。

- 无历史或用户显式开启新话题(history 为空)时直接返回原问题,不调用 LLM(省钱提速)
- 保留商品名/型号/数量等关键实体
"""
# 场景:多轮对话中"它多少钱""那款呢"这类省略式提问,直接拿去检索几乎必败
# 注意:改写只影响检索;最终回答仍用原始问题生成,避免答非所问
import logging

from app.services import llm_service

logger = logging.getLogger(__name__)

# 改写提示词:要求模型输出"独立自包含"的检索问题——多轮口语(如"它呢")单独拿出来无法检索
_REWRITE_PROMPT = (
    "你是对话改写助手。根据多轮对话历史,把最新一条用户问题改写为"
    "独立、自包含的检索问题,用于知识库检索。"
    "要求:\n"
    "1. 保留商品名、型号、规格、数量等关键实体\n"
    "2. 补全代词(它/这个/那款)所指代的商品\n"
    "3. 只输出改写后的问题本身,不要任何解释、前缀或引号\n\n"
    "对话历史:\n{history}\n\n"
    "最新问题:{question}"
)


# 改写:history=最近 N 条消息 [{role, content}],question=当前问题;返回独立可检索的问题
async def rewrite_query(history: list[dict], question: str) -> str:
    """history: [{role, content}] 最近 N 条;返回独立问题。"""
    # 无历史即第一轮对话,问题天然自包含——省一次 LLM 调用(省钱又提速)
    if not history:
        return question
    # 格式化为"用户/助手:内容":模型需要区分说话人,才能正确判断代词指代谁
    # 拼接只读操作,不改动调用方的 history 列表
    history_text = "\n".join(f"{'用户' if h['role'] == 'user' else '助手'}: {h['content']}" for h in history)
    # 历史截断到 1500 字符:超出部分对"补全代词"已无增益,反而增加 token 成本
    # 先限长再 format:防止超长历史把提示词顶出模型的上下文窗口
    prompt = _REWRITE_PROMPT.format(history=history_text[-1500:], question=question)
    try:
        answer = await llm_service.ainvoke([{"role": "user", "content": prompt}])
        # 清洗模型可能多带的引号/括号;空结果回退原问题
        rewritten = answer.strip().strip('"').strip("「」")
        logger.info("问题改写: %s → %s", question[:30], rewritten[:50])
        # 模型输出空串/纯引号时回退原问题,防止"改写成空"导致检索零结果
        return rewritten or question
    except Exception as e:  # noqa: BLE001 改写失败不阻塞问答,回退原问题
        # 改写是"增强"而非"必需":LLM 不可用时用原问题检索,只是多轮场景下召回质量下降
        logger.warning("改写失败,回退原问题: %s", e)
        return question
