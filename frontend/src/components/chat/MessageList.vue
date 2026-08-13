<script setup lang="ts">
/**
 * 消息列表:展示当前会话全部消息与引导卡片，流式回答期间自动吸底滚动。
 */
import { nextTick, ref, watch } from 'vue'
import { useChatStore } from '@/stores/chat'
import MessageItem from './MessageItem.vue'

const store = useChatStore()
const container = ref<HTMLElement | null>(null)
let stickToBottom = true

watch(
  () => store.messages,
  async () => {
    if (stickToBottom) {
      await nextTick()
      container.value?.scrollTo({ top: container.value.scrollHeight, behavior: 'smooth' })
    }
  },
  { deep: true },
)

function onScroll() {
  const el = container.value
  if (!el) return
  stickToBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
}

// 点击推荐示例问题
function quickAsk(q: string) {
  // 直接往输入框或提交
  const inputEl = document.querySelector('textarea')
  if (inputEl) {
    inputEl.value = q
    inputEl.dispatchEvent(new Event('input', { bubbles: true }))
    inputEl.focus()
  }
}
</script>

<template>
  <div ref="container" class="message-list" @scroll="onScroll">
    <!-- 空状态推荐导航 -->
    <div v-if="!store.messages.length" class="empty-welcome">
      <div class="welcome-badge">
        <span class="sparkle">✨</span> RAG Optimization AI Assistant
      </div>
      <h2 class="welcome-title">欢迎使用智能知识库检索问答</h2>
      <p class="welcome-desc">已连接通义千问大模型与 Qdrant 向量数据库，支持精准长文档溯源检索</p>

      <div class="suggested-grid">
        <div class="suggest-card" @click="quickAsk('星云手机 X1 支持几天无理由退换？')">
          <span class="card-icon">📱</span>
          <div class="card-text">
            <strong>退换货政策</strong>
            <span>星云手机 X1 支持几天无理由退换？</span>
          </div>
        </div>

        <div class="suggest-card" @click="quickAsk('星云手机 X1 电池容量与快充功率是多少？')">
          <span class="card-icon">⚡</span>
          <div class="card-text">
            <strong>硬件参数</strong>
            <span>星云手机 X1 电池容量与快充功率是多少？</span>
          </div>
        </div>

        <div class="suggest-card" @click="quickAsk('清风空气净化器适用多大面积？')">
          <span class="card-icon">🍃</span>
          <div class="card-text">
            <strong>产品说明书</strong>
            <span>清风空气净化器适用多大面积？</span>
          </div>
        </div>

        <div class="suggest-card" @click="quickAsk('星云手机 X1 的防水等级是什么？')">
          <span class="card-icon">🛡️</span>
          <div class="card-text">
            <strong>防护等级</strong>
            <span>星云手机 X1 的防水等级是什么？</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 消息列表 -->
    <div v-else class="messages-inner">
      <MessageItem v-for="m in store.messages" :key="m.id" :message="m" />
    </div>
  </div>
</template>

<style scoped>
.message-list {
  flex: 1;
  min-height: 0;
  height: 100%;
  width: 100%;
  overflow-y: auto;
  padding: 24px 32px;
  scroll-behavior: smooth;
  box-sizing: border-box;
}

.messages-inner {
  max-width: 900px;
  margin: 0 auto;
}

.empty-welcome {
  height: 100%;
  max-width: 800px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px 20px;
}

.welcome-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  font-size: 12px;
  font-weight: 600;
  padding: 4px 12px;
  border-radius: 20px;
  margin-bottom: 16px;
  border: 1px solid rgba(99, 102, 241, 0.2);
}

.welcome-title {
  font-size: 24px;
  font-weight: 800;
  color: #0f172a;
  margin: 0 0 10px;
  letter-spacing: -0.5px;
}

.welcome-desc {
  font-size: 14px;
  color: #64748b;
  margin: 0 0 36px;
  max-width: 540px;
  line-height: 1.6;
}

.suggested-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  width: 100%;
}

.suggest-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  padding: 16px;
  text-align: left;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.03);
}

.suggest-card:hover {
  border-color: #6366f1;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -4px rgba(99, 102, 241, 0.15);
}

.card-icon {
  font-size: 22px;
}

.card-text {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.card-text strong {
  font-size: 13px;
  color: #1e293b;
}

.card-text span {
  font-size: 12px;
  color: #64748b;
  line-height: 1.4;
}
</style>
