"""评估模块的请求/响应 Schema。"""
from pydantic import BaseModel, Field


# --- 文档列表 ---
class SampleDocOut(BaseModel):
    """可选的样本文档信息。"""
    name: str
    size_bytes: int
    file_type: str


# --- 出题 ---
class GenerateQuestionsReq(BaseModel):
    """出题请求：指定文档和每文档题目数。"""
    file_names: list[str] = Field(..., min_length=1, description="选中的文档文件名列表")
    num_per_doc: int = Field(3, ge=1, le=10, description="每个文档生成的题目数")


class QuestionItem(BaseModel):
    """单道测试题。"""
    question: str
    ground_truth: str


# --- 评估任务 ---
class StartEvalReq(BaseModel):
    """启动评估请求：传入题目列表和源文档。"""
    questions: list[QuestionItem] = Field(..., min_length=1)
    source_files: list[str] = Field(default_factory=list)


class EvalTaskOut(BaseModel):
    """评估任务状态响应。"""
    id: str
    status: str
    progress: int
    total_questions: int
    current_step: str
    avg_faithfulness: float | None = None
    avg_answer_relevancy: float | None = None
    avg_context_precision: float | None = None
    avg_context_recall: float | None = None
    source_files: str  # JSON 字符串
    error: str | None = None
    created_at: str
    finished_at: str | None = None

    model_config = {"from_attributes": True}


class EvalRecordOut(BaseModel):
    """单条评估明细响应。"""
    id: str
    question: str
    ground_truth: str
    response: str
    retrieved_contexts: str  # JSON 字符串
    faithfulness: float | None = None
    answer_relevancy: float | None = None
    context_precision: float | None = None
    context_recall: float | None = None

    model_config = {"from_attributes": True}
