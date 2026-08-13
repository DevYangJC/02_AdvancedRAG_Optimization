<script setup lang="ts">
/**
 * 知识库管理页:统计卡片 + 文档表格 + 上传 + 删除 + Chunk 预览。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { documentApi } from '@/api/documents'
import type { AdminStats, ChunkItem, DocumentItem } from '@/types/api'

// 文档列表状态
const docs = ref<DocumentItem[]>([])
const total = ref(0)
const stats = ref<AdminStats | null>(null)
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const pageSize = 20

// 上传对话框状态
const uploadVisible = ref(false)
const uploading = ref(false)
const uploadFiles = ref<File[]>([])
const uploadRef = ref<HTMLInputElement | null>(null)

// 切分预览抽屉状态
const previewVisible = ref(false)
const previewDoc = ref<DocumentItem | null>(null)
const previewChunks = ref<ChunkItem[]>([])
const previewTotal = ref(0)
const previewPage = ref(1)
const PREVIEW_PAGE_SIZE = 50

let timer: number | null = null
let statsTimer: number | null = null

const hasActiveTask = computed(() =>
  docs.value.some((d) => d.status === 'processing' || d.status === 'deleting'),
)

async function loadDocs() {
  loading.value = true
  try {
    const { data } = await documentApi.list(page.value, pageSize, keyword.value || undefined)
    docs.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  try {
    const { data } = await documentApi.stats()
    stats.value = data
  } catch {
    /* 403 时隐藏 */
  }
}

function onFileChange(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (files) uploadFiles.value = Array.from(files)
}

function handleDrop(e: DragEvent) {
  const files = e.dataTransfer?.files
  if (files?.length) uploadFiles.value = Array.from(files)
}

async function doUpload() {
  if (!uploadFiles.value.length) return ElMessage.warning('请选择文件')
  uploading.value = true
  try {
    const { data } = await documentApi.upload(uploadFiles.value)
    ElMessage.success(`上传成功 ${data.uploaded} 个文件，正在解析入库…`)
    uploadVisible.value = false
    uploadFiles.value = []
    loadDocs()
  } catch {
    /* 拦截器已处理 */
  } finally {
    uploading.value = false
  }
}

async function onDelete(doc: DocumentItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除"${doc.filename}"? 对应 ${doc.chunk_total} 个知识块与向量将一并删除。`,
      '确认删除',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    await documentApi.remove(doc.id)
    ElMessage.success('已删除')
    loadDocs()
    loadStats()
  } catch {
    /* 取消 */
  }
}

async function openPreview(doc: DocumentItem) {
  previewDoc.value = doc
  previewVisible.value = true
  previewPage.value = 1
  await loadChunks()
}

async function loadChunks() {
  if (!previewDoc.value) return
  const { data } = await documentApi.listChunks(previewDoc.value.id, previewPage.value, PREVIEW_PAGE_SIZE)
  previewChunks.value = data.items
  previewTotal.value = data.total
}

function formatSize(bytes: number | null): string {
  if (!bytes) return '-'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function statusTag(status: string) {
  return {
    ready: { type: 'success' as const, text: '已就绪' },
    processing: { type: 'warning' as const, text: '解析中' },
    failed: { type: 'danger' as const, text: '失败' },
    deleting: { type: 'info' as const, text: '删除中' },
  }[status] ?? { type: 'info' as const, text: status }
}

onMounted(() => {
  loadDocs()
  loadStats()
  timer = window.setInterval(() => {
    if (hasActiveTask.value) loadDocs()
  }, 3000)
  statsTimer = window.setInterval(loadStats, 15000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
  if (statsTimer) clearInterval(statsTimer)
})
</script>

<template>
  <div class="knowledge-workspace">
    <!-- Header -->
    <header class="knowledge-header">
      <div class="header-title-group">
        <h1 class="page-title">文档与知识库管理</h1>
        <span class="page-subtitle">管理文档入库、切分向量索引与全站统计</span>
      </div>
      <el-button type="primary" class="upload-btn" icon="Upload" @click="uploadVisible = true">
        上传知识文档
      </el-button>
    </header>

    <div class="knowledge-content">
      <!-- 统计卡片网格 -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-icon-wrapper blue">
            <el-icon><Document /></el-icon>
          </div>
          <div class="stat-info">
            <span class="stat-label">文档数</span>
            <span class="stat-value">{{ stats?.document_count ?? '-' }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon-wrapper indigo">
            <el-icon><Files /></el-icon>
          </div>
          <div class="stat-info">
            <span class="stat-label">知识块数</span>
            <span class="stat-value">{{ stats?.chunk_count ?? '-' }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon-wrapper violet">
            <el-icon><Cpu /></el-icon>
          </div>
          <div class="stat-info">
            <span class="stat-label">向量数 (Qdrant)</span>
            <span class="stat-value">{{ stats?.vector_count ?? '-' }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon-wrapper emerald">
            <el-icon><ChatLineRound /></el-icon>
          </div>
          <div class="stat-info">
            <span class="stat-label">累计问答</span>
            <span class="stat-value">{{ stats?.total_question_count ?? '-' }}</span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon-wrapper amber">
            <el-icon><Discount /></el-icon>
          </div>
          <div class="stat-info">
            <span class="stat-label">缓存命中率</span>
            <span class="stat-value">
              {{ stats ? (stats.cache_hit_rate * 100).toFixed(1) + '%' : '-' }}
            </span>
          </div>
        </div>

        <div class="stat-card">
          <div class="stat-icon-wrapper rose">
            <el-icon><User /></el-icon>
          </div>
          <div class="stat-info">
            <span class="stat-label">注册用户</span>
            <span class="stat-value">{{ stats?.user_count ?? '-' }}</span>
          </div>
        </div>
      </div>

      <!-- 表格主卡片 -->
      <div class="table-card">
        <div class="toolbar">
          <div class="search-box">
            <el-input
              v-model="keyword"
              placeholder="按文件名搜索..."
              clearable
              prefix-icon="Search"
              style="width: 280px"
              @keyup.enter="loadDocs"
              @clear="loadDocs"
            />
            <el-button type="primary" plain @click="loadDocs">搜索</el-button>
          </div>
          <span class="total-hint">共 {{ total }} 个知识文件</span>
        </div>

        <!-- 文档表格 -->
        <el-table :data="docs" v-loading="loading" class="custom-table" stripe>
          <el-table-column prop="filename" label="文件名" min-width="260" show-overflow-tooltip>
            <template #default="{ row }">
              <div class="file-name-cell">
                <span class="file-icon">📄</span>
                <span class="file-name">{{ row.filename }}</span>
              </div>
            </template>
          </el-table-column>

          <el-table-column prop="file_type" label="类型" width="90">
            <template #default="{ row }">
              <el-tag size="small" effect="plain" class="type-tag">
                {{ row.file_type.toUpperCase() }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="大小" width="110">
            <template #default="{ row }">
              <span class="size-text">{{ formatSize(row.size_bytes) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="状态" width="180">
            <template #default="{ row }">
              <template v-if="row.status === 'processing'">
                <el-progress
                  :percentage="row.chunk_total ? Math.round((row.chunk_processed / row.chunk_total) * 100) : 0"
                  :stroke-width="6"
                  style="width: 130px"
                />
              </template>
              <template v-else>
                <div class="status-cell">
                  <el-tag :type="statusTag(row.status).type" size="small" effect="light">
                    {{ statusTag(row.status).text }}
                  </el-tag>
                  <el-tooltip v-if="row.error" :content="row.error">
                    <el-icon color="#ef4444" class="error-icon"><Warning /></el-icon>
                  </el-tooltip>
                </div>
              </template>
            </template>
          </el-table-column>

          <el-table-column label="知识块数" width="100">
            <template #default="{ row }">
              <span class="chunk-badge">
                {{ row.status === 'ready' ? row.chunk_total : '-' }}
              </span>
            </template>
          </el-table-column>

          <el-table-column prop="created_at" label="上传时间" width="170">
            <template #default="{ row }">
              <span class="time-text">{{ new Date(row.created_at).toLocaleString() }}</span>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                size="small"
                :disabled="row.status !== 'ready'"
                @click="openPreview(row)"
              >
                预览切分
              </el-button>
              <el-button link type="danger" size="small" @click="onDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager-row">
          <el-pagination
            layout="total, prev, pager, next"
            :total="total"
            :page-size="pageSize"
            :current-page="page"
            @current-change="(p: number) => { page = p; loadDocs() }"
          />
        </div>
      </div>
    </div>

    <!-- 上传对话框 -->
    <el-dialog v-model="uploadVisible" title="上传知识库文档" width="540px" destroy-on-close align-center>
      <div class="upload-drop" @click="uploadRef?.click()" @dragover.prevent @drop.prevent="handleDrop">
        <input ref="uploadRef" type="file" multiple hidden :accept="'.pdf,.docx,.xlsx,.txt,.md'" @change="onFileChange" />
        <div class="drop-icon-bg">
          <el-icon class="drop-icon"><UploadFilled /></el-icon>
        </div>
        <p class="drop-title">点击选择文件 或 拖拽至此处</p>
        <p class="drop-tip">支持 PDF, DOCX, XLSX, TXT, MD 格式（单文件 ≤ 50MB）</p>
      </div>

      <div v-if="uploadFiles.length" class="file-preview">
        <el-tag
          v-for="(f, i) in uploadFiles"
          :key="i"
          closable
          size="default"
          class="file-preview-tag"
          @close="uploadFiles.splice(i, 1)"
        >
          📄 {{ f.name }} <span class="file-size">({{ formatSize(f.size) }})</span>
        </el-tag>
      </div>

      <template #footer>
        <el-button @click="uploadVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploading" :disabled="!uploadFiles.length" @click="doUpload">
          开始解析入库
        </el-button>
      </template>
    </el-dialog>

    <!-- Chunk 预览抽屉 -->
    <el-drawer v-model="previewVisible" :title="`切分预览 · ${previewDoc?.filename}`" size="620px">
      <div class="drawer-header-info">
        <span>共 <strong>{{ previewTotal }}</strong> 个切块片段</span>
        <span class="drawer-tag">递归字符切分 (size=500, overlap=50)</span>
      </div>

      <div class="chunk-list">
        <div v-for="c in previewChunks" :key="c.id" class="chunk-card">
          <div class="chunk-card-meta">
            <span class="chunk-idx">Chunk #{{ c.chunk_index }}</span>
            <el-tag v-if="c.page" size="small" type="info">第 {{ c.page }} 页</el-tag>
            <el-tag v-if="c.section" size="small" type="warning">{{ c.section }}</el-tag>
            <span class="chunk-tokens">{{ c.token_count ?? '-' }} tokens</span>
          </div>
          <div class="chunk-body">{{ c.content }}</div>
        </div>
      </div>

      <div class="drawer-pager">
        <el-pagination
          layout="prev, pager, next"
          :total="previewTotal"
          :page-size="PREVIEW_PAGE_SIZE"
          :current-page="previewPage"
          @current-change="(p: number) => { previewPage = p; loadChunks() }"
        />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.knowledge-workspace {
  height: 100%;
  width: 100%;
  background: #f8fafc;
  overflow-y: auto;
  position: relative;
}

.knowledge-header {
  position: sticky;
  top: 0;
  z-index: 20;
  padding: 20px 32px;
  background: rgba(255, 255, 255, 0.95);
  backdrop-filter: blur(12px);
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.page-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 4px;
}

.page-subtitle {
  font-size: 12px;
  color: #64748b;
}

.upload-btn {
  border-radius: 10px;
  padding: 10px 20px;
  font-weight: 600;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  border: none;
  box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
}

.knowledge-content {
  padding: 24px 32px 80px;
  max-width: 1400px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

/* 统计网格 */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.stat-card {
  background: #ffffff;
  border-radius: 14px;
  padding: 16px 20px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 12px -2px rgba(15, 23, 42, 0.04);
  display: flex;
  align-items: center;
  gap: 16px;
  transition: transform 0.2s, box-shadow 0.2s;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 20px -4px rgba(15, 23, 42, 0.08);
}

.stat-icon-wrapper {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #fff;
  flex-shrink: 0;
}

.stat-icon-wrapper.blue { background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%); }
.stat-icon-wrapper.indigo { background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%); }
.stat-icon-wrapper.violet { background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%); }
.stat-icon-wrapper.emerald { background: linear-gradient(135deg, #10b981 0%, #059669 100%); }
.stat-icon-wrapper.amber { background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%); }
.stat-icon-wrapper.rose { background: linear-gradient(135deg, #f43f5e 0%, #e11d48 100%); }

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-label {
  font-size: 12px;
  color: #64748b;
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  margin-top: 2px;
}

/* 表格卡片 */
.table-card {
  background: #ffffff;
  border-radius: 16px;
  border: 1px solid #e2e8f0;
  box-shadow: 0 4px 20px -2px rgba(15, 23, 42, 0.05);
  padding: 20px 24px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.search-box {
  display: flex;
  gap: 8px;
}

.total-hint {
  font-size: 13px;
  color: #64748b;
}

.file-name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-icon {
  font-size: 16px;
}

.file-name {
  font-size: 13px;
  font-weight: 600;
  color: #1e293b;
}

.type-tag {
  font-weight: 600;
  border-radius: 6px;
}

.size-text, .time-text {
  font-size: 12px;
  color: #64748b;
}

.status-cell {
  display: flex;
  align-items: center;
  gap: 6px;
}

.error-icon {
  cursor: pointer;
}

.pager-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* 上传框 */
.upload-drop {
  border: 2px dashed #cbd5e1;
  border-radius: 14px;
  padding: 36px 20px;
  text-align: center;
  background: #f8fafc;
  cursor: pointer;
  transition: all 0.2s;
}

.upload-drop:hover {
  border-color: #6366f1;
  background: rgba(99, 102, 241, 0.03);
}

.drop-icon-bg {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: rgba(99, 102, 241, 0.1);
  color: #6366f1;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 12px;
  font-size: 26px;
}

.drop-title {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin: 0 0 4px;
}

.drop-tip {
  font-size: 12px;
  color: #94a3b8;
  margin: 0;
}

.file-preview {
  margin-top: 14px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.file-preview-tag {
  border-radius: 8px;
}

.file-size {
  color: #64748b;
  margin-left: 4px;
}

/* Chunk Drawer */
.drawer-header-info {
  font-size: 13px;
  color: #475569;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px solid #e2e8f0;
  margin-bottom: 16px;
}

.drawer-tag {
  font-size: 11px;
  background: #f1f5f9;
  padding: 2px 8px;
  border-radius: 6px;
  color: #64748b;
}

.chunk-list {
  max-height: calc(100vh - 180px);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.chunk-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 12px 14px;
}

.chunk-card-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.chunk-idx {
  font-size: 12px;
  font-weight: 700;
  color: #6366f1;
}

.chunk-tokens {
  margin-left: auto;
  font-size: 11px;
  color: #94a3b8;
}

.chunk-body {
  font-size: 13px;
  line-height: 1.6;
  color: #334155;
  white-space: pre-wrap;
  word-break: break-all;
}

.drawer-pager {
  margin-top: 16px;
  display: flex;
  justify-content: flex-end;
}
</style>
