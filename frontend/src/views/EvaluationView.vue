<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getSampleDocs,
  generateQuestions,
  startEvaluation,
  listEvalTasks,
  getEvalTask,
  getEvalRecords,
  deleteEvalTask,
  regenerateEvalReview,
  type SampleDoc,
  type QuestionItem,
  type EvalTask,
  type EvalRecord
} from '@/api/evaluation'

// 数据状态
const docs = ref<SampleDoc[]>([])
const selectedDocs = ref<string[]>([])
const numPerDoc = ref(3)

const questions = ref<QuestionItem[]>([])
const generating = ref(false)

const currentTask = ref<EvalTask | null>(null)
const records = ref<EvalRecord[]>([])
const taskHistory = ref<EvalTask[]>([])
const reviewing = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// 初始化加载文档与历史任务
onMounted(async () => {
  await loadDocs()
  await loadHistory()
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})

async function loadDocs() {
  try {
    const res = await getSampleDocs()
    docs.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '获取文档失败')
  }
}

async function loadHistory() {
  try {
    const res = await listEvalTasks()
    taskHistory.value = res.data
  } catch (e: any) {
    console.error(e)
  }
}

// 出题
async function onGenerate() {
  if (!selectedDocs.value.length) {
    return ElMessage.warning('请至少选择一个文档')
  }
  generating.value = true
  try {
    const res = await generateQuestions(selectedDocs.value, numPerDoc.value)
    questions.value = res.data
    if (!questions.value.length) {
      ElMessage.warning('出题为空，请重试')
    } else {
      ElMessage.success(`成功生成 ${questions.value.length} 道测试题`)
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '出题失败')
  } finally {
    generating.value = false
  }
}

// 移除某道题
function removeQuestion(index: number) {
  questions.value.splice(index, 1)
}

// 启动评估
async function onStartEval() {
  if (!questions.value.length) {
    return ElMessage.warning('题库为空，无法评估')
  }
  try {
    const res = await startEvaluation(questions.value, selectedDocs.value)
    currentTask.value = res.data
    records.value = []
    startPolling()
    ElMessage.success('评估任务已启动')
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '启动评估失败')
  }
}

// 轮询进度
function startPolling() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = setInterval(async () => {
    if (!currentTask.value) return
    try {
      const res = await getEvalTask(currentTask.value.id)
      currentTask.value = res.data
      if (['done', 'failed'].includes(res.data.status)) {
        clearInterval(pollTimer!)
        pollTimer = null
        if (res.data.status === 'done') {
          await loadRecords(res.data.id)
          ElMessage.success('评估已完成')
        } else {
          ElMessage.error(`评估失败: ${res.data.error}`)
        }
        await loadHistory()
      }
    } catch (e) {
      console.error(e)
    }
  }, 2000)
}

async function loadRecords(taskId: string) {
  try {
    const res = await getEvalRecords(taskId)
    records.value = res.data
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '获取明细失败')
  }
}

function viewTask(task: EvalTask) {
  currentTask.value = task
  if (task.status === 'done') {
    loadRecords(task.id)
  } else {
    records.value = []
    if (['pending', 'evaluating'].includes(task.status)) {
      startPolling()
    }
  }
}

// 删除评估记录(含明细)
async function onDeleteTask(task: EvalTask) {
  try {
    await ElMessageBox.confirm(
      `确定删除该次评估记录及其全部明细吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteEvalTask(task.id)
    ElMessage.success('已删除')
    // 若删除的是当前正在查看的任务,清空结果面板
    if (currentTask.value?.id === task.id) {
      currentTask.value = null
      records.value = []
    }
    await loadHistory()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '删除失败')
  }
}

// 重新生成 LLM 评估点评
async function onRegenerateReview() {
  if (!currentTask.value) return
  reviewing.value = true
  try {
    const res = await regenerateEvalReview(currentTask.value.id)
    currentTask.value = { ...currentTask.value, review: res.data.review }
    ElMessage.success('评估点评已更新')
    await loadHistory()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.message || '生成点评失败')
  } finally {
    reviewing.value = false
  }
}

function getScoreTag(val: number | null) {
  if (val === null) return 'info'
  if (val >= 0.7) return 'success'
  if (val >= 0.4) return 'warning'
  return 'danger'
}
</script>

<template>
  <div class="eval-container">
    <div class="header">
      <div class="header-title">
        <el-icon class="header-icon"><DataAnalysis /></el-icon>
        <h2>RAG 检索智能评估</h2>
      </div>
      <p class="header-desc">通过大模型自动生成问答对，多维度量化评估知识库的问答准确率与召回率，驱动系统持续迭代。</p>
    </div>

    <div class="main-grid">
      <!-- 1. 文档选择 -->
      <el-card class="box-card hover-card">
        <template #header>
          <div class="card-header">
            <span class="step-title"><el-tag effect="dark" round class="step-tag">1</el-tag> 选择知识库文档出题</span>
            <el-input-number v-model="numPerDoc" :min="1" :max="10" size="small" />
          </div>
        </template>
        <el-checkbox-group v-model="selectedDocs" class="doc-list">
          <el-checkbox v-for="d in docs" :key="d.id" :value="d.id" class="doc-item" border>
            <div class="doc-item-content">
              <el-icon class="doc-icon"><Document /></el-icon> 
              <span class="doc-name">{{ d.filename }}</span>
              <span class="meta-size">{{ (d.size_bytes / 1024).toFixed(1) }} KB</span>
            </div>
          </el-checkbox>
        </el-checkbox-group>
        <div class="actions">
          <el-button type="primary" :loading="generating" @click="onGenerate" class="generate-btn">
            <el-icon v-if="!generating"><MagicStick /></el-icon>
            自动生成测试题
          </el-button>
        </div>
      </el-card>

      <!-- 2. 题目预览 -->
      <el-card class="box-card hover-card">
        <template #header>
          <div class="card-header">
            <span class="step-title"><el-tag effect="dark" round class="step-tag">2</el-tag> 题目预览与编辑 (共 {{ questions.length }} 题)</span>
            <el-button v-if="questions.length" type="success" @click="onStartEval" class="start-btn">
              <el-icon><VideoPlay /></el-icon> 开始评估
            </el-button>
          </div>
        </template>
        <div v-if="questions.length" class="question-list">
          <div v-for="(q, idx) in questions" :key="idx" class="q-item">
            <div class="q-header">
              <strong class="q-title"><el-tag size="small" type="info">Q{{ idx + 1 }}</el-tag> {{ q.question }}</strong>
              <el-button link type="danger" :icon="Delete" @click="removeQuestion(idx)" class="del-btn" />
            </div>
            <div class="q-ans">
              <span class="ans-label">A:</span> {{ q.ground_truth }}
            </div>
          </div>
        </div>
        <el-empty v-else description="暂无题目，请先在左侧选择文档并生成" :image-size="100" />
      </el-card>
    </div>

    <!-- 3. 评估执行与结果 -->
    <el-card class="result-card hover-card" v-if="currentTask">
      <template #header>
        <div class="card-header">
          <span class="step-title"><el-tag effect="dark" round class="step-tag">3</el-tag> 评估结果面板</span>
          <el-tag :type="currentTask.status === 'done' ? 'success' : currentTask.status === 'failed' ? 'danger' : 'warning'" effect="dark" round>
            {{ currentTask.status.toUpperCase() }}
          </el-tag>
        </div>
      </template>

      <!-- 进度条 -->
      <div v-if="['pending', 'evaluating'].includes(currentTask.status)" class="progress-box">
        <el-progress type="dashboard" :percentage="currentTask.progress" :color="[ { color: '#f56c6c', percentage: 20 }, { color: '#e6a23c', percentage: 40 }, { color: '#5cb87a', percentage: 80 }, { color: '#1989fa', percentage: 100 } ]" />
        <p class="step-text">{{ currentTask.current_step }}</p>
      </div>

      <div v-if="currentTask.error" class="error-box">
        <el-icon><Warning /></el-icon> {{ currentTask.error }}
      </div>

      <!-- 结果汇总 -->
      <div v-if="currentTask.status === 'done'" class="summary-box">
        <div class="score-card">
          <div class="score-title">Faithfulness<br><small>忠实度(无幻觉)</small></div>
          <el-statistic :value="currentTask.avg_faithfulness ?? 0" :precision="4" value-style="color: #409EFF; font-weight: bold; font-size: 24px;" />
        </div>
        <div class="score-card">
          <div class="score-title">Answer Relevancy<br><small>回答相关性</small></div>
          <el-statistic :value="currentTask.avg_answer_relevancy ?? 0" :precision="4" value-style="color: #67C23A; font-weight: bold; font-size: 24px;" />
        </div>
        <div class="score-card">
          <div class="score-title">Context Precision<br><small>上下文精确度</small></div>
          <el-statistic :value="currentTask.avg_context_precision ?? 0" :precision="4" value-style="color: #E6A23C; font-weight: bold; font-size: 24px;" />
        </div>
        <div class="score-card">
          <div class="score-title">Context Recall<br><small>上下文召回率</small></div>
          <el-statistic :value="currentTask.avg_context_recall ?? 0" :precision="4" value-style="color: #F56C6C; font-weight: bold; font-size: 24px;" />
        </div>
      </div>

      <!-- AI 评估建议(LLM 生成的整体点评) -->
      <div v-if="currentTask.status === 'done'" class="review-box">
        <div class="review-header">
          <span>AI 评估建议</span>
          <el-button size="small" text type="primary" :loading="reviewing" @click="onRegenerateReview">
            {{ currentTask.review ? '重新生成' : '生成点评' }}
          </el-button>
        </div>
        <div v-if="currentTask.review" class="review-text">{{ currentTask.review }}</div>
        <div v-else class="review-empty">暂无点评，点击右侧按钮由 LLM 分析本次评估结果（哪个指标最低、建议优化什么）。</div>
      </div>

      <!-- 明细表格 -->
      <el-table v-if="records.length" :data="records" style="width: 100%" max-height="400">
        <el-table-column type="expand">
          <template #default="props">
            <div class="expand-detail">
              <p><strong>大模型回答：</strong>{{ props.row.response }}</p>
              <p><strong>参考答案：</strong>{{ props.row.ground_truth }}</p>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="question" label="问题" show-overflow-tooltip />
        <el-table-column label="Faithfulness" width="120">
          <template #default="{row}">
            <el-tag :type="getScoreTag(row.faithfulness)">{{ row.faithfulness?.toFixed(4) ?? '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Ans. Relevancy" width="120">
          <template #default="{row}">
            <el-tag :type="getScoreTag(row.answer_relevancy)">{{ row.answer_relevancy?.toFixed(4) ?? '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Ctx. Precision" width="120">
          <template #default="{row}">
            <el-tag :type="getScoreTag(row.context_precision)">{{ row.context_precision?.toFixed(4) ?? '-' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="Ctx. Recall" width="120">
          <template #default="{row}">
            <el-tag :type="getScoreTag(row.context_recall)">{{ row.context_recall?.toFixed(4) ?? '-' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 4. 历史记录 -->
    <div class="history-section" v-if="taskHistory.length">
      <h3 class="section-title"><el-icon><Clock /></el-icon> 历史评估记录</h3>
      <div class="history-list">
        <div v-for="t in taskHistory" :key="t.id" class="hist-item" @click="viewTask(t)" :class="{active: currentTask?.id === t.id}">
          <div class="hist-status-bar" :class="t.status"></div>
          <div class="hist-content">
            <div class="hist-top">
              <div class="t-time">{{ new Date(t.created_at).toLocaleString() }}</div>
              <el-icon class="hist-del" title="删除该记录" @click.stop="onDeleteTask(t)"><Delete /></el-icon>
            </div>
            <div class="hist-mid">
              <el-tag size="small" :type="t.status === 'done' ? 'success' : 'info'" effect="light" round>{{ t.status }}</el-tag>
              <span class="t-score" v-if="t.avg_faithfulness">得分: {{ (t.avg_faithfulness * 100).toFixed(1) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.eval-container { 
  padding: 24px 32px; 
  display: flex; 
  flex-direction: column; 
  gap: 24px; 
  overflow-y: auto; 
  height: 100%; 
  background-color: #f8fafc;
}

.header {
  margin-bottom: 8px;
}
.header-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.header-icon {
  font-size: 28px;
  color: #3b82f6;
  background: #dbeafe;
  padding: 8px;
  border-radius: 12px;
}
.header-title h2 { 
  margin: 0; 
  color: #0f172a; 
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.5px;
}
.header-desc { 
  margin: 0 0 0 56px; 
  color: #64748b; 
  font-size: 14px; 
}

.main-grid { 
  display: grid; 
  grid-template-columns: 1fr 1fr; 
  gap: 24px; 
}

.hover-card {
  border: none;
  border-radius: 16px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
  transition: transform 0.2s ease, box-shadow 0.2s ease;
}
.hover-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08), 0 4px 6px -2px rgba(0, 0, 0, 0.04);
}

.card-header { 
  display: flex; 
  justify-content: space-between; 
  align-items: center; 
}
.step-title {
  font-weight: 600;
  font-size: 16px;
  color: #1e293b;
  display: flex;
  align-items: center;
  gap: 8px;
}
.step-tag {
  font-weight: bold;
}

/* 文档选择样式优化 */
.doc-list { 
  display: flex; 
  flex-direction: column; 
  gap: 12px; 
  max-height: 250px; 
  overflow-y: auto; 
  margin-bottom: 20px; 
  padding-right: 8px;
}
.doc-item {
  margin: 0 !important;
  border-radius: 8px;
  padding: 16px;
  height: auto;
  transition: all 0.2s;
  background: white;
}
.doc-item.is-checked {
  background: #eff6ff;
  border-color: #3b82f6;
}
.doc-item-content {
  display: flex;
  align-items: center;
  width: 100%;
}
.doc-icon {
  font-size: 18px;
  margin-right: 8px;
  color: #64748b;
}
.doc-item.is-checked .doc-icon {
  color: #3b82f6;
}
.doc-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.meta-size { 
  color: #94a3b8; 
  font-size: 12px; 
  margin-left: auto; 
}

.actions { text-align: right; }
.generate-btn, .start-btn {
  border-radius: 8px;
  font-weight: 600;
  padding: 10px 20px;
}

/* 题目预览样式优化 */
.question-list { 
  max-height: 320px; 
  overflow-y: auto; 
  display: flex; 
  flex-direction: column; 
  gap: 16px; 
  padding-right: 8px;
}
.q-item { 
  background: #ffffff; 
  padding: 16px; 
  border-radius: 12px; 
  border: 1px solid #e2e8f0; 
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
  transition: border-color 0.2s;
}
.q-item:hover {
  border-color: #cbd5e1;
}
.q-header { 
  display: flex; 
  justify-content: space-between; 
  align-items: flex-start;
  margin-bottom: 12px; 
}
.q-title {
  font-size: 14px;
  color: #0f172a;
  line-height: 1.5;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.del-btn { 
  padding: 4px;
  margin-left: 8px;
}
.q-ans { 
  font-size: 13px; 
  color: #475569; 
  background: #f8fafc;
  padding: 12px;
  border-radius: 6px;
  line-height: 1.6;
}
.ans-label {
  font-weight: bold;
  color: #10b981;
}

/* 进度与结果 */
.progress-box { 
  text-align: center; 
  padding: 40px 20px; 
}
.step-text { 
  margin-top: 20px; 
  color: #64748b; 
  font-weight: 500;
  font-size: 16px;
}
.error-box { 
  color: #ef4444; 
  padding: 16px; 
  background: #fef2f2; 
  border-radius: 8px; 
  border: 1px solid #fecaca;
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 500;
}

/* 4个得分卡片 */
.summary-box { 
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px; 
}
.score-card {
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 20px 16px;
  text-align: center;
  box-shadow: 0 1px 3px rgba(0,0,0,0.02);
}
.score-title {
  color: #64748b;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  line-height: 1.4;
}
.score-title small {
  font-size: 12px;
  font-weight: normal;
  color: #94a3b8;
}

.expand-detail { 
  padding: 20px; 
  background: #f8fafc; 
  font-size: 13px;
  border-radius: 8px;
  margin: 8px 24px;
  border: 1px solid #e2e8f0;
}
.expand-detail p {
  margin: 8px 0;
  line-height: 1.6;
  color: #334155;
}
.expand-detail strong {
  color: #0f172a;
}

/* 历史记录优化 */
.history-section {
  margin-top: 16px;
}
.section-title {
  font-size: 16px;
  color: #1e293b;
  margin: 0 0 16px 0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.history-list { 
  display: flex; 
  gap: 16px; 
  overflow-x: auto; 
  padding-bottom: 12px; 
}
.hist-item { 
  display: flex;
  border: 1px solid #e2e8f0; 
  border-radius: 12px; 
  cursor: pointer; 
  min-width: 220px; 
  background: #fff; 
  overflow: hidden;
  transition: all 0.2s;
  box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}
.hist-item:hover { 
  transform: translateY(-2px);
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.hist-item.active { 
  border-color: #3b82f6; 
  background: #f0f9ff; 
}
.hist-status-bar {
  width: 6px;
  background: #cbd5e1;
}
.hist-status-bar.done { background: #10b981; }
.hist-status-bar.failed { background: #ef4444; }
.hist-status-bar.evaluating, .hist-status-bar.pending { background: #f59e0b; }

.hist-content {
  padding: 14px;
  flex: 1;
}
.hist-top { 
  display: flex; 
  justify-content: space-between; 
  align-items: center; 
  margin-bottom: 12px; 
}
.hist-top .t-time { 
  font-size: 12px; 
  color: #64748b; 
  font-weight: 500;
}
.hist-del { 
  color: #ef4444; 
  cursor: pointer; 
  opacity: 0; 
  transition: opacity 0.2s; 
  padding: 4px;
  border-radius: 4px;
}
.hist-del:hover {
  background: #fee2e2;
}
.hist-item:hover .hist-del { opacity: 1; }

.hist-mid {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.t-score { 
  font-size: 14px; 
  font-weight: 600; 
  color: #0f172a;
}

/* AI 评估建议 */
.review-box { margin-bottom: 24px; padding: 16px 20px; background: linear-gradient(145deg, #f0f7ff, #e0f2fe); border: 1px solid #bae6fd; border-radius: 12px; }
.review-header { display: flex; justify-content: space-between; align-items: center; font-weight: 600; color: #0369a1; margin-bottom: 12px; }
.review-text { font-size: 14px; color: #0f172a; line-height: 1.8; white-space: pre-wrap; }
.review-empty { font-size: 13px; color: #64748b; font-style: italic; }

/* 覆盖 Element Plus 的 Table 样式，更清爽 */
:deep(.el-table) {
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.05);
}
:deep(.el-table th.el-table__cell) {
  background-color: #f1f5f9;
  color: #475569;
  font-weight: 600;
}
</style>
