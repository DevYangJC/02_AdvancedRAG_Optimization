"""中文友好的文本切分。

策略:
- 分隔符序列不含英文句点,避免拆坏 "3.5 英寸" "100.5元" 等电商文案
- MD 文件先按标题层级切(MarkdownHeaderTextSplitter),再递归切
- chunk_size=500 适中,overlap=50 保持语义连续
"""
# 为什么切分:向量检索的粒度单位是 chunk——块太大语义混杂,太小上下文割裂
# chunk_size=500 字符适中:单块信息量够模型回答,又不会因过长稀释关键信息
# chunk_overlap=50 字符:相邻块重叠,跨块句子不被拦腰截断,语义保持连续
# 切分不修改原文:只产出新 Chunk 对象,加载结果可复用
import logging
from dataclasses import dataclass

from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.core.config import settings
from app.rag.loaders import TextBlock

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    # index 在整个文档范围内连续递增:入库与展示顺序一致,检索命中位置可回推
    index: int
    content: str
    # page/section 是来源定位:检索命中时前端展示"第几页/哪一章",增强回答可信度
    page: int | None = None
    section: str | None = None


# 中文友好分隔符序列:段→行→句→子句→词→字符(不含英文句点)
# 末尾的空串是兜底:最坏情况按单字切,保证切分永不失败
_CHINESE_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", "、", " ", ""]


# 工厂:切分参数统一取自配置,调整 chunk 大小无需改代码
def _make_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        # 为什么递归切分:优先满足大分隔符(段落边界),整段超长才降级用更细的分隔符
        separators=_CHINESE_SEPARATORS,
        # len 按字符计数:中文每字 1,与 token 估算量级一致
        length_function=len,
    )


# 普通文本切分:一个文本块 → 若干 chunk,index 从 start_index 连续分配,编号不重不漏
# start_index 由外部传入:多个文本块共享同一全局编号序列
def _split_plain(block: TextBlock, start_index: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    # 超长段落会产出多个 chunk:按分隔符边界自然断开
    for piece in _make_splitter().split_text(block.text):
        chunks.append(
            # page/section 从文本块透传:块内所有 chunk 继承来源页码与章节
            Chunk(index=start_index + len(chunks), content=piece, page=block.page, section=block.section)
        )
    return chunks


def _split_markdown(block: TextBlock, start_index: int) -> list[Chunk]:
    """MD:先按标题层级切,保留标题作为 section,再对正文递归切。"""
    # 只切到 H4:更深层标题多为细节补充,单独成块反而碎片化
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "H1"), ("##", "H2"), ("###", "H3"), ("####", "H4")],
        # 标题保留在正文:chunk 自带小标题语义,检索匹配更准确
        strip_headers=False,
    )
    chunks: list[Chunk] = []
    # 每个标题章节独立切分:章节边界不会跨 chunk,引用定位更精确
    try:
        docs = splitter.split_text(block.text)
    except Exception as e:  # noqa: BLE001 标题不完整时回退普通切分
        # md 结构损坏(如标题未闭合)不阻塞入库:退回普通切分,只是丢失章节定位
        logger.warning("Markdown 切分回退普通切分: %s", e)
        return _split_plain(block, start_index)
    for doc in docs:
        # 嵌套标题用 / 连接(如"产品介绍 / 规格参数"):层级信息不丢失
        section = " / ".join(str(v) for _, v in doc.metadata.items())
        for piece in _make_splitter().split_text(doc.page_content):
            chunks.append(
                Chunk(
                    index=start_index + len(chunks),
                    content=piece,
                    page=block.page,
                    # 优先 md 标题层级,缺省回退块的原始 section
                    section=section or block.section,
                )
            )
    return chunks


# 切分入口:blocks=加载出的文本块、is_markdown=是否按 Markdown 层级切;返回全局连续编号的 Chunk 列表
# blocks 为空时返回空列表:入库任务据此判断"无可入库内容"
def split_blocks(blocks: list[TextBlock], is_markdown: bool = False) -> list[Chunk]:
    """将加载出的文本块切分为带索引的 chunk 序列。"""
    chunks: list[Chunk] = []
    # 大文档切分是 CPU 密集操作:调用方(入库任务)应通过 to_thread 包裹,避免阻塞事件循环
    for block in blocks:
        # 只有 md 文件且块未被加载器标注章节时才走 md 切分:避免重复切分
        if is_markdown and block.section is None:
            chunks.extend(_split_markdown(block, len(chunks)))
        else:
            chunks.extend(_split_plain(block, len(chunks)))
    # 日志记录切分规模:用于评估 chunk 数量与 embedding 成本
    logger.info("切分完成: %d 块 → %d chunks", len(blocks), len(chunks))
    return chunks
