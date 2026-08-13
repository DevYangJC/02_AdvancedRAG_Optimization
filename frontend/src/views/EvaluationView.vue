<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getSampleDocs,
  generateQuestions,
  startEvaluation,
  listEvalTasks,
  getEvalTask,
  getEvalRecords,
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
      <h2>RAG 检索评估</h2>
      <p>通过大模型自动生成问答对，量化评估 RAG 知识库的问答准确率与召回率。</p>
    </div>

    <div class="main-grid">
      <!-- 1. 文档选择 -->
      <el-card class="box-card">
        <template #header>
          <div class="card-header">
            <span>1. 选择文档出题</span>
            <el-input-number v-model="numPerDoc" :min="1" :max="10" size="small" label="每文档出题数" />
          </div>
        </template>
        <el-checkbox-group v-model="selectedDocs" class="doc-list">
          <el-checkbox v-for="d in docs" :key="d.name" :value="d.name">
            <el-icon><Document /></el-icon> {{ d.name }}
            <span class="meta-size">{{ (d.size_bytes / 1024).toFixed(1) }} KB</span>
          </el-checkbox>
        </el-checkbox-group>
        <div class="actions">
          <el-button type="primary" :loading="generating" @click="onGenerate">自动生成测试题</el-button>
        </div>
      </el-card>

      <!-- 2. 题目预览 -->
      <el-card class="box-card">
        <template #header>
          <div class="card-header">
            <span>2. 题目预览与编辑 (共 {{ questions.length }} 题)</span>
            <el-button v-if="questions.length" type="success" @click="onStartEval">开始评估</el-button>
          </div>
        </template>
        <div v-if="questions.length" class="question-list">
          <div v-for="(q, idx) in questions" :key="idx" class="q-item">
            <div class="q-header">
              <strong>Q: {{ q.question }}</strong>
              <el-icon class="del-btn" @click="removeQuestion(idx)"><Delete /></el-icon>
            </div>
            <div class="q-ans">A: {{ q.ground_truth }}</div>
          </div>
        </div>
        <el-empty v-else description="暂无题目，请先选择文档出题" />
      </el-card>
    </div>

    <!-- 3. 评估执行与结果 -->
    <el-card class="result-card" v-if="currentTask">
      <template #header>
        <div class="card-header">
          <span>3. 评估结果面板</span>
          <el-tag :type="currentTask.status === 'done' ? 'success' : currentTask.status === 'failed' ? 'danger' : 'warning'">
            {{ currentTask.status.toUpperCase() }}
          </el-tag>
        </div>
      </template>

      <!-- 进度条 -->
      <div v-if="['pending', 'evaluating'].includes(currentTask.status)" class="progress-box">
        <el-progress :percentage="currentTask.progress" />
        <p class="step-text">{{ currentTask.current_step }}</p>
      </div>

      <div v-if="currentTask.error" class="error-box">{{ currentTask.error }}</div>

      <!-- 结果汇总 -->
      <div v-if="currentTask.status === 'done'" class="summary-box">
        <el-statistic title="Faithfulness" :value="currentTask.avg_faithfulness ?? 0" />
        <el-statistic title="Answer Relevancy" :value="currentTask.avg_answer_relevancy ?? 0" />
        <el-statistic title="Context Precision" :value="currentTask.avg_context_precision ?? 0" />
        <el-statistic title="Context Recall" :value="currentTask.avg_context_recall ?? 0" />
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
    <el-card class="history-card" v-if="taskHistory.length">
      <template #header>
        <span>历史评估记录</span>
      </template>
      <div class="history-list">
        <div v-for="t in taskHistory" :key="t.id" class="hist-item" @click="viewTask(t)" :class="{active: currentTask?.id === t.id}">
          <div class="t-time">{{ new Date(t.created_at).toLocaleString() }}</div>
          <el-tag size="small" :type="t.status === 'done' ? 'success' : 'info'">{{ t.status }}</el-tag>
          <div class="t-score" v-if="t.avg_faithfulness">得分: {{ t.avg_faithfulness }}</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.eval-container { padding: 24px; display: flex; flex-direction: column; gap: 20px; overflow-y: auto; height: 100%; }
.header h2 { margin: 0 0 8px 0; color: #1e293b; }
.header p { margin: 0; color: #64748b; font-size: 14px; }
.main-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
.card-header { display: flex; justify-content: space-between; align-items: center; font-weight: 600; }
.doc-list { display: flex; flex-direction: column; gap: 8px; max-height: 200px; overflow-y: auto; margin-bottom: 16px; }
.meta-size { color: #94a3b8; font-size: 12px; margin-left: 8px; }
.actions { text-align: right; }
.question-list { max-height: 300px; overflow-y: auto; display: flex; flex-direction: column; gap: 12px; }
.q-item { background: #f8fafc; padding: 12px; border-radius: 8px; border: 1px solid #e2e8f0; }
.q-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
.del-btn { color: #f87171; cursor: pointer; }
.q-ans { font-size: 13px; color: #64748b; }
.progress-box { text-align: center; padding: 20px; }
.step-text { margin-top: 12px; color: #64748b; }
.summary-box { display: flex; justify-content: space-around; padding: 20px 0; border-bottom: 1px solid #e2e8f0; margin-bottom: 16px; }
.expand-detail { padding: 16px; background: #f8fafc; font-size: 13px; }
.error-box { color: #ef4444; padding: 12px; background: #fef2f2; border-radius: 4px; }
.history-list { display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px; }
.hist-item { padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px; cursor: pointer; min-width: 150px; background: #fff; }
.hist-item:hover { border-color: #cbd5e1; }
.hist-item.active { border-color: #3b82f6; background: #eff6ff; }
.t-time { font-size: 12px; color: #64748b; margin-bottom: 8px; }
.t-score { font-size: 13px; margin-top: 8px; font-weight: 500; }
</style>
