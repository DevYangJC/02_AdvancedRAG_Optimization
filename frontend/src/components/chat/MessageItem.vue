<script setup lang="ts">
/**
 * 单条消息组件: Markdown 渲染 + 引用编号 + 来源卡片 + 流式打字与反馈。
 */
import { computed, ref } from 'vue'
import { renderMarkdown } from '@/composables/useMarkdown'
import { useChatStore } from '@/stores/chat'
import type { Message, SourceRef } from '@/types/api'

const props = defineProps<{ message: Message }>()
const store = useChatStore()

const html = computed(() => renderMarkdown(props.message.content, props.message.sources?.length ?? 0))
const activeSource = ref<SourceRef | null>(null)

function onCiteClick(e: MouseEvent) {
  const cite = (e.target as HTMLElement).closest('.cite')
  if (!cite || cite.classList.contains('cite-invalid')) return
  const idx = Number(cite.getAttribute('data-cite'))
  const source = props.message.sources?.find((s) => s.index === idx)
  if (!source) return
  activeSource.value = activeSource.value?.index === idx ? null : source
}

async function onFeedback(value: number) {
  if (props.message.feedback === value) return
  await store.setFeedback(props.message.id, value)
}
</script>

<template>
  <div class="message-row" :class="message.role">
    <!-- 头像 -->
    <div class="avatar-box">
      <div v-if="message.role === 'assistant'" class="ai-avatar">
        <svg class="ai-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M12 2L14.5 9.5L22 12L14.5 14.5L12 22L9.5 14.5L2 12L9.5 9.5L12 2Z" fill="currentColor"/>
        </svg>
      </div>
      <div v-else class="user-avatar">
        <span>我</span>
      </div>
    </div>

    <!-- 消息主体 -->
    <div class="message-body">
      <div class="bubble">
        <!-- 引用展开详情弹层 -->
        <div v-if="activeSource" class="source-popover">
          <div class="sp-header">
            <span class="sp-title">📄 {{ activeSource.doc_title }}</span>
            <span class="sp-score">匹配度 {{ (activeSource.score * 100).toFixed(1) }}%</span>
          </div>
          <div class="sp-sub-info" v-if="activeSource.page || activeSource.section">
            <span v-if="activeSource.page">第 {{ activeSource.page }} 页</span>
            <span v-if="activeSource.section">· {{ activeSource.section }}</span>
          </div>
          <div class="sp-snippet">{{ activeSource.snippet }}</div>
        </div>

        <!-- 消息正文 -->
        <div v-if="message.role === 'assistant'" class="md-body" @click="onCiteClick" v-html="html" />
        <div v-else class="plain-body">{{ message.content }}</div>

        <!-- 打字动画光标 -->
        <div v-if="message.status === 'streaming'" class="streaming-cursor" />

        <!-- 中断提示 -->
        <div v-if="message.status === 'error'" class="error-tip">
          <el-icon><Warning /></el-icon> 生成异常中断，已保留已收到内容
        </div>
      </div>

      <!-- 引用来源 Chips -->
      <div v-if="message.sources?.length" class="sources-bar">
        <span class="sources-label">引用来源:</span>
        <div
          v-for="s in message.sources"
          :key="s.index"
          class="source-chip"
          :class="{ active: activeSource?.index === s.index }"
          @click="activeSource = activeSource?.index === s.index ? null : s"
        >
          <span class="chip-idx">[{{ s.index }}]</span>
          <span class="chip-title">{{ s.doc_title }}</span>
          <span class="chip-page" v-if="s.page">P.{{ s.page }}</span>
        </div>
      </div>

      <!-- 反馈点赞点踩 -->
      <div v-if="message.role === 'assistant' && message.status !== 'streaming'" class="feedback-row">
        <button
          class="fb-btn"
          :class="{ active: message.feedback === 1 }"
          title="有帮助"
          @click="onFeedback(1)"
        >
          👍 有帮助
        </button>
        <button
          class="fb-btn"
          :class="{ active: message.feedback === -1 }"
          title="没帮助"
          @click="onFeedback(-1)"
        >
          👎 需改进
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-row {
  display: flex;
  gap: 16px;
  margin-bottom: 24px;
}

.message-row.user {
  flex-direction: row-reverse;
}

.avatar-box {
  flex-shrink: 0;
}

.ai-avatar {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.25);
}

.ai-icon {
  width: 20px;
  height: 20px;
}

.user-avatar {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 14px;
  box-shadow: 0 4px 10px rgba(59, 130, 246, 0.25);
}

.message-body {
  max-width: 82%;
  min-width: 0;
}

.message-row.user .message-body {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.bubble {
  position: relative;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 16px;
  padding: 14px 18px;
  color: #1e293b;
  font-size: 14px;
  line-height: 1.7;
  box-shadow: 0 4px 12px -2px rgba(15, 23, 42, 0.03);
}

.message-row.user .bubble {
  background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
  color: #ffffff;
  border: none;
  box-shadow: 0 4px 14px rgba(79, 70, 229, 0.25);
}

.plain-body {
  white-space: pre-wrap;
  word-break: break-word;
}

.md-body {
  word-break: break-all;
}

.md-body :deep(p) {
  margin: 6px 0;
}

.md-body :deep(pre) {
  background: #0f172a;
  color: #f1f5f9;
  border-radius: 10px;
  padding: 14px;
  overflow-x: auto;
  font-family: 'Fira Code', Consolas, Monaco, monospace;
  font-size: 13px;
  line-height: 1.5;
}

.md-body :deep(code:not(pre code)) {
  background: #f1f5f9;
  color: #6366f1;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 13px;
  font-weight: 600;
}

.md-body :deep(table) {
  border-collapse: collapse;
  margin: 10px 0;
  width: 100%;
}

.md-body :deep(th, td) {
  border: 1px solid #cbd5e1;
  padding: 6px 12px;
  font-size: 13px;
}

.md-body :deep(th) {
  background: #f8fafc;
  font-weight: 600;
}

.streaming-cursor {
  display: inline-block;
  width: 8px;
  height: 16px;
  margin-left: 4px;
  vertical-align: -2px;
  background: #6366f1;
  animation: blink 0.8s infinite;
  border-radius: 2px;
}

@keyframes blink {
  50% { opacity: 0; }
}

.error-tip {
  margin-top: 8px;
  color: #ef4444;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.sources-bar {
  margin-top: 10px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.sources-label {
  font-size: 12px;
  color: #64748b;
  font-weight: 500;
}

.source-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #e2e8f0;
  cursor: pointer;
  transition: all 0.2s;
  max-width: 260px;
}

.source-chip:hover {
  background: rgba(99, 102, 241, 0.08);
  border-color: rgba(99, 102, 241, 0.3);
  color: #6366f1;
}

.source-chip.active {
  background: #6366f1;
  color: #fff;
  border-color: #6366f1;
}

.chip-idx {
  font-weight: 700;
}

.chip-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-page {
  font-size: 11px;
  opacity: 0.8;
}

.feedback-row {
  margin-top: 8px;
  display: flex;
  gap: 8px;
}

.fb-btn {
  background: transparent;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 3px 10px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.2s;
}

.fb-btn:hover {
  border-color: #cbd5e1;
  color: #1e293b;
}

.fb-btn.active {
  background: rgba(99, 102, 241, 0.1);
  border-color: #6366f1;
  color: #6366f1;
  font-weight: 600;
}

/* 引用弹层 */
.source-popover {
  margin-bottom: 12px;
  padding: 12px 14px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  border-radius: 12px;
  font-size: 13px;
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.08);
}

.sp-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 4px;
}

.sp-title {
  font-weight: 700;
  color: #b45309;
}

.sp-score {
  font-size: 11px;
  color: #d97706;
  font-weight: 600;
  background: rgba(245, 158, 11, 0.15);
  padding: 1px 6px;
  border-radius: 4px;
}

.sp-sub-info {
  font-size: 11px;
  color: #d97706;
  margin-bottom: 6px;
}

.sp-snippet {
  color: #451a03;
  line-height: 1.6;
  max-height: 100px;
  overflow-y: auto;
  font-size: 12px;
  white-space: pre-wrap;
}
</style>
