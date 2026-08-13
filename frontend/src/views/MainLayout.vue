<script setup lang="ts">
/**
 * 全局主布局组件:一站式侧边栏主导航(知识问答 / 文档管理) + 动态工作区。
 * 融合顶部品牌、模块切换导航、问答会话管理与底部用户面板。
 */
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

const auth = useAuthStore()
const chat = useChatStore()
const route = useRoute()
const router = useRouter()

// 侧边栏折叠状态
const isCollapsed = ref(false)

// 当前搜索会话关键词
const sessionSearch = ref('')

// 改名状态
const editingId = ref<string | null>(null)
const editingTitle = ref('')

// 修改密码弹窗
const pwdDialog = ref(false)
const pwdForm = ref({ old_password: '', new_password: '', confirm: '' })
const pwdSaving = ref(false)

// 过滤后的会话列表
const filteredConversations = computed(() => {
  if (!sessionSearch.value.trim()) return chat.conversations
  return chat.conversations.filter((c) =>
    c.title.toLowerCase().includes(sessionSearch.value.trim().toLowerCase()),
  )
})

// 当前激活的模块名
const activeNav = computed(() => {
  if (route.path.startsWith('/admin/knowledge')) return 'knowledge'
  return 'chat'
})

// 用户头像简称
const userAvatarText = computed(() => {
  const name = auth.user?.nickname || auth.user?.username || 'U'
  return name.slice(0, 2).toUpperCase()
})

// 会话改名
function startRename(conv: any) {
  editingId.value = conv.id
  editingTitle.value = conv.title
}

async function confirmRename(conv: any) {
  if (editingTitle.value.trim() && editingTitle.value.trim() !== conv.title) {
    await chat.rename(conv.id, editingTitle.value.trim())
  }
  editingId.value = null
}

// 会话删除
async function onDelete(conv: any) {
  try {
    await ElMessageBox.confirm(`确定删除会话"${conv.title}"? 历史消息将一并删除。`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await chat.remove(conv.id)
    ElMessage.success('已删除会话')
  } catch {
    /* 取消 */
  }
}

// 格式化会话更新时间
function formatTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  const sameDay = d.toDateString() === now.toDateString()
  return sameDay
    ? `${pad(d.getHours())}:${pad(d.getMinutes())}`
    : `${d.getMonth() + 1}/${d.getDate()}`
}

// 导航跳转
function navigateTo(target: 'chat' | 'knowledge') {
  if (target === 'knowledge') {
    if (!auth.isAdmin()) {
      ElMessage.warning('文档管理需管理员权限')
      return
    }
    router.push('/admin/knowledge')
  } else {
    router.push('/chat')
  }
}

// 退出登录
function onLogout() {
  auth.logout()
  router.push('/login')
}

// 密码修改
function openPasswordDialog() {
  pwdForm.value = { old_password: '', new_password: '', confirm: '' }
  pwdDialog.value = true
}

async function savePassword() {
  const { old_password, new_password, confirm } = pwdForm.value
  if (!old_password || !new_password) return ElMessage.warning('请填写完整')
  if (new_password.length < 6) return ElMessage.warning('新密码至少 6 位')
  if (new_password !== confirm) return ElMessage.warning('两次密码不一致')

  pwdSaving.value = true
  try {
    await auth.changePassword(old_password, new_password)
    ElMessage.success('密码修改成功，请重新登录')
    pwdDialog.value = false
    auth.logout()
    router.push('/login')
  } catch {
    /* 拦截器已处理 */
  } finally {
    pwdSaving.value = false
  }
}
</script>

<template>
  <div class="app-layout" :class="{ 'is-collapsed': isCollapsed }">
    <!-- 主侧边栏 -->
    <aside class="main-sidebar">
      <!-- 1. 品牌 Header -->
      <div class="brand-header">
        <div class="brand-logo">
          <svg class="logo-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M12 2L2 7L12 12L22 7L12 2Z"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <path
              d="M2 17L12 22L22 17"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <path
              d="M2 12L12 17L22 12"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </div>
        <div v-if="!isCollapsed" class="brand-info">
          <span class="brand-title">RAG 智能知识库</span>
          <span class="brand-subtitle">Enterprise Optimization</span>
        </div>
        <button class="collapse-toggle" @click="isCollapsed = !isCollapsed" :title="isCollapsed ? '展开侧边栏' : '折叠侧边栏'">
          <el-icon><Expand v-if="isCollapsed" /><Fold v-else /></el-icon>
        </button>
      </div>

      <!-- 2. 主功能导航 (知识问答 / 文档管理) -->
      <div class="nav-section">
        <div class="section-label" v-if="!isCollapsed">核心功能</div>
        <nav class="nav-menu">
          <div
            class="nav-item"
            :class="{ active: activeNav === 'chat' }"
            @click="navigateTo('chat')"
            title="知识问答"
          >
            <el-icon class="nav-icon"><ChatDotRound /></el-icon>
            <span v-if="!isCollapsed" class="nav-text">知识问答</span>
            <span v-if="!isCollapsed && chat.conversations.length" class="nav-badge">
              {{ chat.conversations.length }}
            </span>
          </div>

          <div
            class="nav-item"
            :class="{ active: activeNav === 'knowledge' }"
            @click="navigateTo('knowledge')"
            title="文档管理"
          >
            <el-icon class="nav-icon"><FolderOpened /></el-icon>
            <span v-if="!isCollapsed" class="nav-text">文档管理</span>
            <span v-if="!isCollapsed && auth.isAdmin()" class="admin-tag">Admin</span>
          </div>
        </nav>
      </div>

      <!-- 3. 问答会话历史 (仅在知识问答页面或非折叠模式展现) -->
      <div v-if="activeNav === 'chat' && !isCollapsed" class="session-section">
        <div class="session-header">
          <span class="section-label">会话列表</span>
          <button class="new-chat-btn" @click="chat.newConversation()" title="新建会话">
            <el-icon><Plus /></el-icon> 新建
          </button>
        </div>

        <!-- 搜索过滤框 -->
        <div class="session-search">
          <el-input
            v-model="sessionSearch"
            placeholder="搜索历史会话..."
            size="small"
            clearable
            prefix-icon="Search"
          />
        </div>

        <!-- 滚动列表 -->
        <div class="session-list">
          <div
            v-for="conv in filteredConversations"
            :key="conv.id"
            class="session-item"
            :class="{ active: chat.current?.id === conv.id }"
            @click="chat.selectConversation(conv.id)"
          >
            <el-icon class="item-icon"><ChatLineSquare /></el-icon>

            <template v-if="editingId === conv.id">
              <el-input
                v-model="editingTitle"
                size="small"
                class="rename-input"
                autofocus
                @keyup.enter="confirmRename(conv)"
                @blur="confirmRename(conv)"
                @click.stop
              />
            </template>
            <template v-else>
              <span class="session-title" :title="conv.title">{{ conv.title }}</span>
              <div class="session-actions" @click.stop>
                <el-icon class="act-btn" title="重命名" @click="startRename(conv)"><Edit /></el-icon>
                <el-icon class="act-btn danger" title="删除" @click="onDelete(conv)"><Delete /></el-icon>
              </div>
            </template>
            <span class="session-time">{{ formatTime(conv.updated_at) }}</span>
          </div>

          <div v-if="!filteredConversations.length" class="session-empty">
            {{ sessionSearch ? '未找到相关会话' : '暂无历史会话' }}
          </div>
        </div>
      </div>

      <!-- 4. 底部用户卡片 -->
      <div class="user-section">
        <el-dropdown trigger="click" placement="top-start" style="width: 100%">
          <div class="user-card">
            <div class="avatar">{{ userAvatarText }}</div>
            <div v-if="!isCollapsed" class="user-meta">
              <span class="user-nickname">{{ auth.user?.nickname || auth.user?.username }}</span>
              <span class="user-role">{{ auth.isAdmin() ? '系统管理员' : '普通成员' }}</span>
            </div>
            <el-icon v-if="!isCollapsed" class="caret-icon"><MoreFilled /></el-icon>
          </div>

          <template #dropdown>
            <el-dropdown-menu class="user-dropdown-menu">
              <div class="dropdown-header">
                <strong>{{ auth.user?.username }}</strong>
                <span class="role-badge" :class="{ admin: auth.isAdmin() }">
                  {{ auth.isAdmin() ? '管理员' : '标准用户' }}
                </span>
              </div>
              <el-dropdown-item divided @click="openPasswordDialog">
                <el-icon><Lock /></el-icon> 修改密码
              </el-dropdown-item>
              <el-dropdown-item divided command="logout" @click="onLogout">
                <el-icon><SwitchButton /></el-icon> 退出登录
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </aside>

    <!-- 工作区主体内容 -->
    <main class="main-content">
      <router-view />
    </main>

    <!-- 修改密码弹窗 -->
    <el-dialog v-model="pwdDialog" title="修改个人密码" width="420px" destroy-on-close align-center>
      <el-form label-position="top">
        <el-form-item label="当前旧密码">
          <el-input v-model="pwdForm.old_password" type="password" show-password placeholder="请输入原密码" />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="pwdForm.new_password" type="password" show-password placeholder="至少 6 位新密码" />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input
            v-model="pwdForm.confirm"
            type="password"
            show-password
            placeholder="再次输入新密码"
            @keyup.enter="savePassword"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pwdDialog = false">取消</el-button>
        <el-button type="primary" :loading="pwdSaving" @click="savePassword">保存修改</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background-color: #f8fafc;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
}

/* 侧边栏整体 */
.main-sidebar {
  width: 260px;
  height: 100%;
  background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
  color: #f8fafc;
  display: flex;
  flex-direction: column;
  border-right: 1px solid rgba(255, 255, 255, 0.08);
  transition: width 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  user-select: none;
  z-index: 20;
}

.is-collapsed .main-sidebar {
  width: 72px;
}

/* 品牌 Header */
.brand-header {
  height: 64px;
  padding: 0 16px;
  display: flex;
  align-items: center;
  gap: 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.brand-logo {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, #6366f1 0%, #3b82f6 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.35);
  flex-shrink: 0;
}

.logo-icon {
  width: 22px;
  height: 22px;
}

.brand-info {
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow: hidden;
}

.brand-title {
  font-size: 15px;
  font-weight: 700;
  color: #f1f5f9;
  letter-spacing: 0.3px;
  white-space: nowrap;
}

.brand-subtitle {
  font-size: 10px;
  color: #94a3b8;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.collapse-toggle {
  background: transparent;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 6px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
}

.collapse-toggle:hover {
  background: rgba(255, 255, 255, 0.1);
  color: #f8fafc;
}

/* Section Label */
.section-label {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  color: #64748b;
  margin-bottom: 8px;
  padding: 0 8px;
}

/* 模块导航区 */
.nav-section {
  padding: 16px 12px 12px;
}

.nav-menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  border-radius: 10px;
  color: #94a3b8;
  cursor: pointer;
  transition: all 0.2s ease;
  position: relative;
}

.nav-item:hover {
  background: rgba(255, 255, 255, 0.06);
  color: #f1f5f9;
}

.nav-item.active {
  background: linear-gradient(90deg, rgba(99, 102, 241, 0.2) 0%, rgba(99, 102, 241, 0.05) 100%);
  color: #818cf8;
  font-weight: 600;
  border-left: 3px solid #6366f1;
}

.nav-icon {
  font-size: 18px;
  flex-shrink: 0;
}

.nav-text {
  font-size: 14px;
  flex: 1;
}

.nav-badge {
  background: rgba(99, 102, 241, 0.2);
  color: #a5b4fc;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 12px;
  font-weight: 600;
}

.admin-tag {
  background: linear-gradient(135deg, #ec4899 0%, #f43f5e 100%);
  color: #fff;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  font-weight: 700;
}

/* 会话模块 */
.session-section {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 8px 12px;
  overflow: hidden;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.session-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 4px 4px 8px;
}

.new-chat-btn {
  background: rgba(99, 102, 241, 0.15);
  border: 1px solid rgba(99, 102, 241, 0.3);
  color: #c7d2fe;
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 4px;
  transition: all 0.2s;
}

.new-chat-btn:hover {
  background: #6366f1;
  color: #fff;
  box-shadow: 0 4px 10px rgba(99, 102, 241, 0.3);
}

.session-search {
  margin-bottom: 8px;
}

.session-search :deep(.el-input__wrapper) {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: none;
  color: #e2e8f0;
  border-radius: 6px;
}

.session-search :deep(.el-input__inner) {
  color: #e2e8f0;
}

.session-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding-right: 2px;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  color: #94a3b8;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
  position: relative;
}

.session-item:hover {
  background: rgba(255, 255, 255, 0.05);
  color: #cbd5e1;
}

.session-item.active {
  background: rgba(255, 255, 255, 0.08);
  color: #f8fafc;
  font-weight: 500;
}

.item-icon {
  font-size: 15px;
  flex-shrink: 0;
  opacity: 0.7;
}

.session-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-actions {
  display: none;
  align-items: center;
  gap: 6px;
}

.session-item:hover .session-actions {
  display: flex;
}

.act-btn {
  font-size: 13px;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
}

.act-btn:hover {
  color: #818cf8;
}

.act-btn.danger:hover {
  color: #f87171;
}

.session-time {
  font-size: 11px;
  color: #64748b;
  flex-shrink: 0;
}

.session-item:hover .session-time {
  display: none;
}

.session-empty {
  text-align: center;
  color: #64748b;
  font-size: 12px;
  padding: 24px 0;
}

/* 底部用户区 */
.user-section {
  padding: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.user-card {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.2s;
}

.user-card:hover {
  background: rgba(255, 255, 255, 0.06);
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
  color: #fff;
  font-weight: 700;
  font-size: 13px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.3);
}

.user-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.user-nickname {
  font-size: 13px;
  font-weight: 600;
  color: #f1f5f9;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.user-role {
  font-size: 11px;
  color: #64748b;
}

.caret-icon {
  color: #64748b;
  font-size: 14px;
}

/* 工作区主体 */
.main-content {
  flex: 1;
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  position: relative;
}

/* Dropdown Menu Customization */
.user-dropdown-menu {
  min-width: 180px;
  padding: 6px;
}

.dropdown-header {
  padding: 8px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
  margin-bottom: 4px;
}

.role-badge {
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 4px;
  background: #e2e8f0;
  color: #475569;
}

.role-badge.admin {
  background: #ffe4e6;
  color: #e11d48;
}
</style>
