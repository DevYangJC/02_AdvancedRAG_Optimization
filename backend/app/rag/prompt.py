"""RAG 问答提示词与上下文拼装。"""

# 系统提示词:回答规则的"宪法",写在 system 位置,模型优先遵守
SYSTEM_PROMPT = """你是一个电商平台智能客服助手,基于提供的知识库内容回答用户关于商品的问题。

回答规则:
1. 仅依据知识库内容回答,严禁编造知识库中不存在的信息
2. 引用格式:在引用知识的句子末尾标注编号,格式为 [1] [2],编号对应"知识库片段"的顺序
3. 每条回答必须引用至少一个知识库片段;若知识库中找不到相关信息,如实说明"知识库中暂未找到相关信息",不要编造
4. 综合多个片段回答时确保信息一致;片段间矛盾时优先采信更具体的描述
5. 使用简体中文,语气亲切专业,像真实的电商客服
6. 不要提及"知识库""片段""检索"等内部概念"""
# 规则 3 是引用机制的核心:回答必须引用证据,无引用的回答将被视为不可信
# 规则 6 维持客服人设:不让模型自曝 RAG 内部流程,增强用户信任感


# 拼装知识库片段为模型可见的证据文本:编号 [n] 即引用编号,模型回答中引用才可对应
def build_context(ranked_chunks: list[dict]) -> str:
    """按候选顺序编号拼装知识库片段(编号顺序 = 引用编号 [n] 的映射)。"""
    parts = []
    for i, chunk in enumerate(ranked_chunks, start=1):
        # 兼容三种数据结构:直接 content、qdrant payload 里的 chunk_content 或 text
        content = chunk.get("content") or chunk.get("payload", {}).get("chunk_content") or chunk.get("payload", {}).get("text") or ""
        parts.append(f"[{i}] {content}")
    # 片段间空行分隔:降低模型把相邻片段误读为同一段落的概率
    return "\n\n".join(parts)


# 拼装最终用户提示词(与 chain.py 的 human 模板等价,供非链式调用复用)
def build_user_prompt(context: str, question: str) -> str:
    return f"知识库片段:\n{context}\n\n用户问题:{question}"
