/**
 * Markdown 渲染 + 代码高亮 + 引用编号 [n] 后处理
 *
 * 渲染流程:markdown-it 全量渲染 → 正则把 [n] 替换为 <cite> 引用节点
 * 引用节点样式由 MessageItem.vue 全局定义;点击事件用事件委托处理。
 */
import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
  highlight(code: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        return `<pre class="hljs"><code>${hljs.highlight(code, { language: lang }).value}</code></pre>`
      } catch {
        /* fallthrough */
      }
    }
    return `<pre class="hljs"><code>${md.utils.escapeHtml(code)}</code></pre>`
  },
})

/**
 * 渲染 markdown 文本为 HTML,并把 [n] 引用编号替换为可点击的 <cite>。
 * maxIndex: 引用最大编号(越界视为幻觉编号,置灰不可点)。
 */
export function renderMarkdown(text: string, maxIndex: number): string {
  let html = md.render(text)
  html = html.replace(
    /\[(\d+)\]/g,
    (_m, idx: string) => {
      const n = Number(idx)
      if (n < 1 || n > maxIndex) return `<cite class="cite cite-invalid">[${n}]</cite>`
      return `<cite class="cite" data-cite="${n}">[${n}]</cite>`
    },
  )
  return html
}
