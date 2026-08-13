<script setup lang="ts">
/**
 * 聊天主工作台:消息流 + 悬浮输入框 + SSE 流式编排。
 */
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { streamChat } from '@/composables/useSSE'
import { useChatStore } from '@/stores/chat'
import MessageList from '@/components/chat/MessageList.vue'
import type { Message } from '@/types/api'

const chat = useChatStore()

// 输入框状态
const input = ref('')
const sending = ref(false)
const inputRef = ref<HTMLTextAreaElement | null>(null)

// 提问主流程
async function onSubmit() {
  const content = input.value.trim()
  if (!content || sending.value) return

  if (!chat.current) {
    await chat.newConversation()
  }
  const convId = chat.current!.id
  sending.value = true
  input.value = ''
  
  // 用户消息立即上屏
  chat.pushLocalUser(content)

  // 助手占位消息
  const aiMsg: Message = chat.pushLocalAssistant(null)
  chat.stream.status = 'streaming'

  const { ok, error } = await streamChat(
    { conversation_id: convId, content },
    {
      onMeta: (sources) => {
        aiMsg.sources = sources
      },
      onDelta: (text) => {
        aiMsg.content += text
        chat.stream.status = 'streaming'
      },
      onDone: () => {
        aiMsg.status = 'completed'
        chat.stream.status = 'done'
        if (chat.conversations.find((c) => c.id === convId)?.title === '新对话') {
          setTimeout(() => chat.loadConversations(), 1500)
        }
      },
      onError: (_code, message) => {
        aiMsg.status = 'error'
        chat.stream.status = 'error'
        chat.stream.errorMsg = message
        ElMessage.error(message)
      },
    },
  )

  if (!ok && !chat.stream.errorMsg) {
    aiMsg.status = 'error'
    chat.stream.status = 'error'
    chat.stream.errorMsg = error || '回答生成失败'
    if (error) ElMessage.error(error)
  }
  sending.value = false
  inputRef.value?.focus()
}

// 键盘快捷键
function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    onSubmit()
  }
}

onMounted(async () => {
  await chat.loadConversations()
  if (chat.conversations.length) {
    await chat.selectConversation(chat.conversations[0].id)
  }
  inputRef.value?.focus()
})
</script>

<template>
  <div class="chat-workspace">
    <!-- 顶部 Header -->
    <header class="chat-header">
      <div class="header-left">
        <h1 class="header-title">{{ chat.current?.title || '新知识问答' }}</h1>
        <el-tag v-if="chat.current" size="small" type="primary" effect="light" class="conv-tag">
          {{ chat.messages.length }} 条消息
        </el-tag>
      </div>
      <div class="header-right">
        <el-button size="small" plain icon="Plus" @click="chat.newConversation()">
          新建对话
        </el-button>
      </div>
    </header>

    <!-- 消息流区域 -->
    <div class="message-container">
      <MessageList />
    </div>

    <!-- 底部悬浮输入卡片区 -->
    <div class="input-container">
      <div class="input-card">
        <el-input
          ref="inputRef"
          v-model="input"
          type="textarea"
          :rows="2"
          :autosize="{ minRows: 2, maxRows: 6 }"
          :placeholder="sending ? 'AI 思考并回答中...' : '输入你的问题（Enter 发送，Shift+Enter 换行）'"
          resize="none"
          :disabled="sending"
          class="custom-textarea"
          @keydown="onKeydown"
        />
        <div class="input-footer">
          <div class="input-hint">
            <span class="sparkle-icon">✨</span>
            <span class="hint-text">检索问答已开启 RAG 混合增强召回与动态重排序</span>
          </div>
          <el-button
            type="primary"
            class="send-btn"
            :loading="sending"
            :disabled="!input.trim()"
            @click="onSubmit"
          >
            <span v-if="!sending">发送问答</span>
            <span v-else>生成中</span>
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-workspace {
  display: flex;
  flex-direction: column;
  height: 100%;
  width: 100%;
  background: #f8fafc;
  position: relative;
}

/* 顶部 Header */
.chat-header {
  height: 60px;
  padding: 0 28px;
  background: rgba(255, 255, 255, 0.85);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  z-index: 10;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.header-title {
  font-size: 16px;
  font-weight: 700;
  color: #0f172a;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-tag {
  border-radius: 12px;
  font-weight: 500;
}

/* 消息流区域 */
.message-container {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* 底部输入卡片 */
.input-container {
  padding: 16px 28px 24px;
  background: linear-gradient(180deg, rgba(248, 250, 252, 0) 0%, #f8fafc 100%);
}

.input-card {
  max-width: 900px;
  margin: 0 auto;
  background: #ffffff;
  border: 1px solid #cbd5e1;
  border-radius: 16px;
  padding: 14px 16px 12px;
  box-shadow: 0 10px 25px -5px rgba(15, 23, 42, 0.08), 0 8px 10px -6px rgba(15, 23, 42, 0.04);
  transition: all 0.2s ease;
}

.input-card:focus-within {
  border-color: #6366f1;
  box-shadow: 0 12px 30px -5px rgba(99, 102, 241, 0.18), 0 0 0 3px rgba(99, 102, 241, 0.12);
}

.custom-textarea :deep(.el-textarea__inner) {
  border: none;
  box-shadow: none !important;
  padding: 0;
  font-size: 14px;
  line-height: 1.6;
  color: #1e293b;
  background: transparent;
}

.input-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
  padding-top: 10px;
  border-top: 1px solid #f1f5f9;
}

.input-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #64748b;
}

.sparkle-icon {
  font-size: 13px;
}

.send-btn {
  border-radius: 10px;
  padding: 8px 20px;
  font-weight: 600;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
  transition: all 0.2s ease;
}

.send-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
}
</style>
