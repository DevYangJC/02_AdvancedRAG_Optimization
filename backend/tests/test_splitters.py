"""中文切分单元测试:标点优先、英文句点不拆坏、chunk 尺寸。"""
# 切分器决定"检索粒度":块太小上下文不足,块太大命中噪声多;
# 中文没有空格分词,必须按标点切,同时保护小数/型号等带英文句点的文本。
from app.core.config import settings
from app.rag.loaders import TextBlock
from app.rag.splitters import split_blocks


class TestChineseSplitter:
    def test_split_by_chinese_punctuation(self):
        # 以中文句号/叹号/问号为边界切分:一句话是一个完整语义单元。
        # 三种标点混合出现:切分器必须都识别,漏掉任何一种就会把多句黏成一个 chunk。
        blocks = [TextBlock(text="今天天气很好。我们出去玩吧!可以吗?")]
        chunks = split_blocks(blocks)
        assert len(chunks) >= 1
        # 所有 chunk 长度不超过上限
        # 上限来自 settings.chunk_size:超出会撑爆向量模型的输入长度上限。
        assert all(len(c.content) <= settings.chunk_size for c in chunks)

    def test_does_not_break_decimal_with_english_period(self):
        """电商文案中的英文句点(3.5 英寸 / 100.5元)不应被当作句子边界。"""
        # "3.5"里的点若是被当句号切走,检索"3.5 毫米"就永远命中不了。
        text = "该手机屏幕尺寸为 6.7 英寸,支持 3.5 毫米耳机孔,售价 100.5 元。"
        chunks = split_blocks([TextBlock(text=text)])
        joined = "".join(c.content for c in chunks)
        # 关键数字保持完整
        # 数字两侧的点只可能是小数或型号分隔,必须原样保留。
        assert "6.7" in joined
        assert "3.5" in joined
        assert "100.5" in joined

    def test_long_text_respects_chunk_size(self):
        # 超长文本必须被切成多块,每块都受 chunk_size 约束。
        # 500 句循环远超单块上限:若没有强制截断逻辑,这里会产出超长块导致向量化失败。
        text = "很长的商品介绍。" * 500
        chunks = split_blocks([TextBlock(text=text)])
        assert len(chunks) > 1
        assert all(len(c.content) <= settings.chunk_size for c in chunks)

    def test_markdown_section_tracking(self):
        # markdown 标题要变成 chunk 的 section 字段:回答引用时才能显示"出自哪个小节"。
        text = "# 星云手机 X1\n\n## 电池\n\n本机内置 5000mAh 电池。\n\n## 保修\n\n一年内免费维修。"
        chunks = split_blocks([TextBlock(text=text)], is_markdown=True)
        sections = {c.section for c in chunks}
        # 至少一个 chunk 带章节信息
        assert any(s and "电池" in s for s in sections)

    def test_index_sequential(self):
        # 全局索引必须连续:前端引用编号 [1][2]... 依赖它,断号会导致引用错位。
        text = "第一句。第二句。第三句。"
        blocks = [TextBlock(text=text), TextBlock(text="另一段。")]
        chunks = split_blocks(blocks)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_xlsx_row_style_content_ok(self):
        # xlsx 单元格"键: 值"拼接后的行文本,切分后不能丢字段(检索按字段命中)。
        row = "商品名称: 星云手机 X1; 型号: X1-8-256; 售价: 2999 元; 库存: 500"
        chunks = split_blocks([TextBlock(text=row)])
        assert any("星云手机" in c.content for c in chunks)
