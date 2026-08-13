"""LCEL RAG 管线唯一入口。

- 用 LangChain 表达式语言(LCEL)组装:prompt → llm
- 检索/重排等步骤在 chat_service 中编排,此处只负责"生成"环节
- 若后续需要加分支逻辑(改写重试、工具调用),可无痛迁移到 LangGraph StateGraph
"""
# LCEL(LangChain 表达式语言):用 | 管道把提示词模板与模型串成一条链,链对象可整体复用
# 本模块只负责"生成"环节:检索/重排等步骤在 chat_service 中编排,职责边界清晰
import logging

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

from app.rag.prompt import SYSTEM_PROMPT
from app.services import llm_service

logger = logging.getLogger(__name__)

# 全局单例链:prompt 模板与模型实例都是只读的,反复重建只会浪费资源
_chat_pipeline: Runnable | None = None


# 构建 LCEL 链:system + history + 知识库片段 + 问题 → 流式回答;惰性构建,首问才组装
# 幂等:重复调用返回同一实例,不会重复组装;无参数,返回 Runnable 链(可 invoke/astream)
def build_chat_pipeline() -> Runnable:
    """构建 LCEL 链:system + history + 知识库片段 + 问题 → 流式回答。"""
    global _chat_pipeline
    if _chat_pipeline is None:
        # 模板三段式:system 定回答规则 → history 注入多轮 → human 放知识库证据与问题
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", SYSTEM_PROMPT),
                # MessagesPlaceholder 支持变长历史:多轮消息原样注入,无需预先拼成文本
                MessagesPlaceholder(variable_name="history"),
                # context 是检索/重排后的证据文本;question 用原始问题而非改写后的问题
                ("human", "知识库片段:\n{context}\n\n用户问题:{question}"),
            ]
        )
        # prompt | llm:管道符号,左端输出自动喂给右端输入;Runnable 统一支持 stream/invoke
        _chat_pipeline = prompt | llm_service.get_llm()
        # 链构建不发起网络请求:真正的模型调用发生在 astream 时
        # 全局单例也意味着:换模型后需调用 reset_pipeline 才会重建
        logger.info("LCEL 问答链已构建")
    return _chat_pipeline


# 测试用:重建链(LLM 单例变化时调用);只影响内存中的单例,进行中的流式请求不受影响
def reset_pipeline() -> None:
    """测试用:重建链(LLM 单例变化时调用)。"""
    global _chat_pipeline
    _chat_pipeline = None
