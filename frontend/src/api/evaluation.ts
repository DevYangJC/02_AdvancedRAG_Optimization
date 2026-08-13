/**
 * RAG 评估模块 API 调用封装。
 */
import client from './client'

export interface SampleDoc {
  id: string
  filename: string
  size_bytes: number
  file_type: string
}

export interface QuestionItem {
  question: string
  ground_truth: string
}

export interface EvalTask {
  id: string
  status: string
  progress: number
  total_questions: number
  current_step: string
  avg_faithfulness: number | null
  avg_answer_relevancy: number | null
  avg_context_precision: number | null
  avg_context_recall: number | null
  source_files: string
  error: string | null
  /** LLM 生成的整体评估点评(最低指标+优化建议) */
  review: string | null
  created_at: string
  finished_at: string | null
}

export interface EvalRecord {
  id: string
  question: string
  ground_truth: string
  response: string
  retrieved_contexts: string
  faithfulness: number | null
  answer_relevancy: number | null
  context_precision: number | null
  context_recall: number | null
}

/** 获取可选文档列表 */
export const getSampleDocs = () => client.get<SampleDoc[]>('/evaluation/docs')

/** 根据选中文档生成测试题 */
export const generateQuestions = (doc_ids: string[], num_per_doc = 3) =>
  client.post<QuestionItem[]>('/evaluation/generate', { doc_ids, num_per_doc })

/** 启动评估任务 */
export const startEvaluation = (questions: QuestionItem[], source_files: string[]) =>
  client.post<EvalTask>('/evaluation/start', { questions, source_files })

/** 获取历史评估任务列表 */
export const listEvalTasks = () => client.get<EvalTask[]>('/evaluation/tasks')

/** 获取单个任务状态(轮询用) */
export const getEvalTask = (taskId: string) => client.get<EvalTask>(`/evaluation/tasks/${taskId}`)

/** 获取评估明细结果 */
export const getEvalRecords = (taskId: string) =>
  client.get<EvalRecord[]>(`/evaluation/tasks/${taskId}/records`)

/** 删除评估任务及其全部明细记录 */
export const deleteEvalTask = (taskId: string) =>
  client.delete<{ ok: boolean }>(`/evaluation/tasks/${taskId}`)

/** 重新生成某任务的 LLM 评估点评(最低指标+优化建议) */
export const regenerateEvalReview = (taskId: string) =>
  client.post<{ review: string }>(`/evaluation/tasks/${taskId}/review`)
