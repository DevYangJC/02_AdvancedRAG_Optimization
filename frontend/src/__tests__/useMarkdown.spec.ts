/** useMarkdown 渲染函数单元测试 */
import { describe, it, expect } from 'vitest'
import { renderMarkdown } from '@/composables/useMarkdown'

describe('renderMarkdown', () => {
  it('渲染基础 markdown 语法', () => {
    const html = renderMarkdown('**加粗文字** 和 `行内代码`', 0)
    expect(html).toContain('<strong>加粗文字</strong>')
    expect(html).toContain('<code>行内代码</code>')
  })

  it('把 [n] 引用编号替换为可点击的 cite 节点', () => {
    const html = renderMarkdown('支持 7 天无理由退换 [1]。', 6)
    expect(html).toContain('<cite class="cite" data-cite="1">[1]</cite>')
  })

  it('多个引用编号依次渲染', () => {
    const html = renderMarkdown('电池 5000mAh [1],支持 66W 快充 [2]。', 6)
    expect(html).toContain('data-cite="1"')
    expect(html).toContain('data-cite="2"')
  })

  it('越界引用编号(幻觉)置灰且不可点击', () => {
    const html = renderMarkdown('知识库中未找到相关信息 [9]。', 6)
    expect(html).toContain('cite-invalid')
    expect(html).not.toContain('data-cite="9"')
  })

  it('sources 为空时任何编号都视为越界', () => {
    const html = renderMarkdown('回答 [1]', 0)
    expect(html).toContain('cite-invalid')
  })

  it('代码块高亮(js)', () => {
    const html = renderMarkdown('```js\nconst a = 1\n```', 0)
    expect(html).toContain('hljs')
  })

  it('普通文本安全转义(不注入 HTML)', () => {
    const html = renderMarkdown('<script>alert(1)</script>', 0)
    expect(html).not.toContain('<script>alert')
  })

  it('保留换行与链接', () => {
    const html = renderMarkdown('第一行\n第二行', 0)
    expect(html).toContain('第一行')
    expect(html).toContain('第二行')
  })
})
