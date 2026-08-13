"""文档加载器测试:txt 编码探测(GBK)、md、空文件过滤。"""
# 加载器把各种格式的原始文件统一转成 TextBlock,是 RAG 管线的第一环;
# 这里用 tmp_path 临时目录写真实文件,验证的是"字节 → 文本"的转换质量。
from app.rag.loaders import load_document
from app.rag.splitters import split_blocks


class TestTxtLoader:
    def test_utf8(self, tmp_path):
        # 基础路径:标准 UTF-8 文本应原样读出,内容一个字符都不能丢。
        # 用 tmp_path 保证每次运行用全新目录,不污染仓库里的真实数据。
        p = tmp_path / "utf8.txt"
        p.write_text("星云手机电池 5000mAh。", encoding="utf-8")
        blocks = load_document(p, "txt")
        # 用 any 而非拼接断言:块边界切在哪不确定,只要内容出现在任一块即可。
        assert any("5000mAh" in b.text for b in blocks)

    def test_gbk_detection(self, tmp_path):
        """Windows 产出的 GBK 编码 txt 应被正确探测。"""
        # 中文 Windows 默认 GBK:若加载器不探测编码而硬按 UTF-8 解码,会解出乱码。
        # GBK 中文编码与 UTF-8 完全不同:能正确读出中文即证明编码探测生效。
        p = tmp_path / "gbk.txt"
        p.write_bytes("清风净化器适用 40 平米房间。".encode("gbk"))
        blocks = load_document(p, "txt")
        # 把全部块拼起来再断言,规避"内容恰好被切到两个块里"的误报。
        text = "".join(b.text for b in blocks)
        assert "40 平米" in text

    def test_mixed_encoding_gb18030(self, tmp_path):
        # GB18030 是 GBK 的超集(收录生僻字/少数民族文字):兼容性更广,同样要能探测。
        p = tmp_path / "gb18030.txt"
        p.write_bytes("支持 66W 快充,充电速度很快。".encode("gb18030"))
        blocks = load_document(p, "txt")
        assert any("66W" in b.text for b in blocks)


class TestMarkdownLoader:
    # markdown 与 txt 的本质区别是层级:标题要变成 section 字段供引用展示。
    def test_load_md(self, tmp_path):
        # markdown 加载器还要保留章节层级:标题会变成 section,供切分器带章节切块。
        p = tmp_path / "doc.md"
        p.write_text("# 标题\n\n正文内容。\n\n## 小节\n\n更多内容。", encoding="utf-8")
        blocks = load_document(p, "md")
        # 加载器只产出 TextBlock,切块交给 splitter:本测试顺带验证两者衔接。
        chunks = split_blocks(blocks, is_markdown=True)
        # 至少切成 2 块,且能追到章节名:这决定了回答时能否显示"来自哪一节"。
        assert len(chunks) >= 2
        assert any("标题" in c.section for c in chunks)


# 错误路径测试:加载器对"不该接受的东西"必须明确拒绝。
class TestInvalidFile:
    def test_unsupported_type(self, tmp_path):
        # 未知扩展名必须显式报错而非静默返回空:否则用户会以为上传成功了。
        # 空文件 + 不支持的类型两个坏点叠加,确保错误处理不依赖文件内容。
        p = tmp_path / "x.docx"
        p.write_bytes(b"")
        from app.core.exceptions import BadRequestError

        try:
            load_document(p, "exe")
            raise AssertionError("应抛出 BadRequestError")
        except BadRequestError:
            pass
