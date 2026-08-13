<script setup lang="ts">
/**
 * 会话侧边栏:新建 / 列表 / 重命名 / 删除 / 用户菜单。
 * 会话数据的读写全部委托给 chat store,组件只负责交互与展示。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

// 三个全局状态入口:auth(登录态)、chat(会话数据)、router(页面跳转)。
const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()

// editingId / editingTitle 是一对状态:记录"正在改名的会话 id"与输入框内容,
// 模板据此在"标题"和"输入框"两种形态之间切换。
const editingId = ref<string | null>(null)
const editingTitle = ref('')

// 进入改名态:先把旧标题回填到输入框,用户在此基础上修改,而不是从空白开始。
function startRename(conv: any) {
  editingId.value = conv.id
  editingTitle.value = conv.title
}

// 提交改名:标题非空且确实发生变化才发请求;回车与失焦都会触发,重复触发天然幂等。
async function confirmRename(conv: any) {
  if (editingTitle.value.trim() && editingTitle.value.trim() !== conv.title) {
    await chat.rename(conv.id, editingTitle.value.trim())
  }
  editingId.value = null
}

// 删除前必须二次确认:会话会连带全部历史消息一起删除,且不可恢复。
async function onDelete(conv: any) {
  try {
    await ElMessageBox.confirm(`确定删除会话"${conv.title}"?历史消息将一并删除`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await chat.remove(conv.id)
    ElMessage.success('已删除')
  } catch {
    /* 用户取消 */
  }
}

// 相对时间展示:当天显示"时:分",非当天显示"月/日",贴近聊天工具的阅读习惯。
function formatTime(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  // padStart 补零:避免出现 "9:5" 这种不齐整的时间格式。
  const pad = (n: number) => String(n).padStart(2, '0')
  // 用日期字符串比较是否为同一天:toDateString 不受时区偏移影响。
  const sameDay = d.toDateString() === now.toDateString()
  return sameDay
    ? `${pad(d.getHours())}:${pad(d.getMinutes())}`
    : `${d.getMonth() + 1}/${d.getDate()}`
}

// 登出:由 auth store 统一清空 token 与用户信息,再跳回登录页。
async function onLogout() {
  auth.logout()
  router.push('/login')
}

function showChangePassword() {
  // 由 ChatView 通过事件上抛处理,保持侧边栏专注会话
  emit('change-password')
}

// 声明向父组件抛出的事件:修改密码的弹窗由 ChatView 负责,侧边栏只发信号。
const emit = defineEmits<{ (e: 'change-password'): void }>()
</script>

<template>
  <!-- 侧边栏:固定宽度、纵向三段布局(头部 / 会话列表 / 底部用户区) -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <span class="logo">📚 智能知识库</span>
    </div>

    <!-- 新建会话:直接委托 chat store,创建成功后会自动出现在下方列表 -->
    <el-button type="primary" class="new-btn" @click="chat.newConversation()">＋ 新建会话</el-button>

    <div class="conv-list">
      <!-- 会话项:点击切换当前会话,激活项高亮;悬停才显示操作按钮 -->
      <div
        v-for="conv in chat.conversations"
        :key="conv.id"
        class="conv-item"
        :class="{ active: chat.current?.id === conv.id }"
        @click="chat.selectConversation(conv.id)"
      >
        <!-- 改名模式:输入框独占一行,回车或失焦都提交 -->
        <template v-if="editingId === conv.id">
          <el-input
            v-model="editingTitle"
            size="small"
            autofocus
            @keyup.enter="confirmRename(conv)"
            @blur="confirmRename(conv)"
            @click.stop
          />
        </template>
        <!-- 普通模式:标题 + 操作按钮;@click.stop 防止点按钮时误触发"切换会话" -->
        <template v-else>
          <span class="conv-title">{{ conv.title }}</span>
          <span class="conv-actions">
            <el-icon class="action-icon" @click.stop="startRename(conv)"><Edit /></el-icon>
            <el-icon class="action-icon danger" @click.stop="onDelete(conv)"><Delete /></el-icon>
          </span>
        </template>
        <!-- 更新时间:由 formatTime 格式化为"今天几点"或"月/日" -->
        <div class="conv-time">{{ formatTime(conv.updated_at) }}</div>
      </div>
      <!-- 空列表:引导用户创建第一个会话 -->
      <div v-if="!chat.conversations.length" class="conv-empty">暂无会话,点击上方按钮新建</div>
    </div>

    <!-- 底部用户区:昵称 + 管理员标签 + 下拉菜单,整体可点击展开 -->
    <div class="sidebar-footer">
      <el-dropdown trigger="click" @command="(cmd: string) => (cmd === 'password' ? showChangePassword() : onLogout())">
        <span class="user-badge">
          <span class="user-name">{{ auth.user?.nickname || auth.user?.username }}</span>
          <el-tag v-if="auth.isAdmin()" size="small" type="danger" effect="plain">管理员</el-tag>
          <el-icon><ArrowDown /></el-icon>
        </span>
        <template #dropdown>
          <el-dropdown-menu>
            <!-- 管理员专属入口:知识库管理页;普通用户看不到这一项 -->
            <el-dropdown-item v-if="auth.isAdmin()" command="admin" @click="router.push('/admin/knowledge')">
              📁 知识库管理
            </el-dropdown-item>
            <el-dropdown-item command="password">🔑 修改密码</el-dropdown-item>
            <el-dropdown-item divided command="logout">🚪 退出登录</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
    </div>
  </aside>
</template>

<style scoped>
/* 侧边栏:固定 260px 宽度、占满整屏高度,与聊天区用浅色底 + 右边框分隔 */
.sidebar {
  width: 260px;
  height: 100%;
  background: #f5f7fa;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}
/* 头部:上内边距大于下内边距,让标题更靠近列表,视觉重心下移 */
.sidebar-header {
  padding: 16px 16px 8px;
  font-size: 16px;
  font-weight: 700;
  color: #303133;
}
/* 新建按钮:与侧边留白对齐,并让按钮与头部拉开一点距离 */
.new-btn {
  margin: 8px 12px 4px;
}
/* 会话列表:占满剩余高度(flex:1),会话多时在容器内滚动 */
.conv-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
/* 会话项:整行可点,圆角悬停反馈;position:relative 为后续浮层定位预留 */
.conv-item {
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 2px;
  position: relative;
}
/* 悬停浅灰底:提示"这行可点",但不打扰当前的选中高亮 */
.conv-item:hover {
  background: #eef1f5;
}
/* 激活项浅蓝底:与全局主题色一致,当前会话一目了然 */
.conv-item.active {
  background: #ecf5ff;
}
/* 标题:170px 内省略号截断,防止超长会话名撑乱整行布局 */
.conv-title {
  display: inline-block;
  max-width: 170px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
  color: #303133;
}
/* 操作按钮:默认隐藏,列表保持干净,只有悬停时才浮出 */
.conv-actions {
  float: right;
  display: none;
}
.conv-item:hover .conv-actions {
  display: inline-flex;
}
/* 图标按钮:默认灰色,悬停变主题色;删除(danger)悬停变红色 */
.action-icon {
  font-size: 14px;
  color: #909399;
  margin-left: 6px;
}
.action-icon:hover {
  color: #409eff;
}
.action-icon.danger:hover {
  color: #f56c6c;
}
/* 时间:最小号浅灰,弱化在标题之下,不抢主体信息 */
.conv-time {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 2px;
}
/* 空列表提示:居中且弱化,存在但不喧宾夺主 */
.conv-empty {
  text-align: center;
  color: #c0c4cc;
  font-size: 13px;
  padding: 24px 0;
}
/* 底部用户区:上边框与列表区断开,明确"这是另一块功能" */
.sidebar-footer {
  padding: 12px;
  border-top: 1px solid #e4e7ed;
}
/* 用户徽标:昵称 + 标签 + 箭头横排,整体可点开下拉菜单 */
.user-badge {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #606266;
}
/* 昵称:120px 内截断,用户名过长时保持徽标紧凑不换行 */
.user-name {
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
