"""RAG 评估接口(仅 admin)：文档列表 / 出题 / 启动评估 / 查询结果。"""
import logging

from fastapi import APIRouter

from app.core.deps import AdminUser, DbDep
from app.schemas.evaluation import (
    EvalRecordOut,
    EvalTaskOut,
    GenerateQuestionsReq,
    QuestionItem,
    SampleDocOut,
    StartEvalReq,
)
from app.services import eval_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.get("/docs", response_model=list[SampleDocOut])
async def get_sample_docs(db: DbDep, _admin: AdminUser):
    """获取可选的已入库文档列表。"""
    return await eval_service.list_eval_docs(db)


@router.post("/generate", response_model=list[QuestionItem])
async def generate_questions(req: GenerateQuestionsReq, db: DbDep, _admin: AdminUser):
    """根据选定文档使用 LLM 生成测试题目。"""
    questions = await eval_service.generate_questions(db, req.doc_ids, req.num_per_doc)
    return questions


@router.post("/start", response_model=EvalTaskOut)
async def start_evaluation(req: StartEvalReq, _admin: AdminUser):
    """创建评估任务并后台执行。"""
    questions = [{"question": q.question, "ground_truth": q.ground_truth} for q in req.questions]
    task = await eval_service.create_and_run_task(questions, req.source_files)
    return EvalTaskOut.model_validate(task)


@router.get("/tasks", response_model=list[EvalTaskOut])
async def list_tasks(db: DbDep, _admin: AdminUser):
    """获取历史评估任务列表。"""
    tasks = await eval_service.list_tasks(db)
    return [EvalTaskOut.model_validate(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=EvalTaskOut)
async def get_task(task_id: str, db: DbDep, _admin: AdminUser):
    """获取单个评估任务状态。"""
    task = await eval_service.get_task(db, task_id)
    if not task:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("评估任务不存在")
    return EvalTaskOut.model_validate(task)


@router.get("/tasks/{task_id}/records", response_model=list[EvalRecordOut])
async def get_task_records(task_id: str, db: DbDep, _admin: AdminUser):
    """获取评估任务的明细结果。"""
    records = await eval_service.get_task_records(db, task_id)
    return [EvalRecordOut.model_validate(r) for r in records]


@router.delete("/tasks/{task_id}")
async def delete_eval_task(task_id: str, db: DbDep, _admin: AdminUser):
    """删除评估任务及其全部明细记录。"""
    ok = await eval_service.delete_task(db, task_id)
    if not ok:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("评估任务不存在")
    return {"ok": True}


@router.post("/tasks/{task_id}/review")
async def regenerate_review(task_id: str, db: DbDep, _admin: AdminUser):
    """重新生成某任务的 LLM 评估点评(最低指标+优化建议)。"""
    review = await eval_service.regenerate_review(db, task_id)
    if review is None:
        from app.core.exceptions import NotFoundError
        raise NotFoundError("评估任务不存在")
    return {"review": review}
