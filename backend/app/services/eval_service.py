"""RAG 评估核心业务服务。

职责：
- 扫描可选文档列表
- 调用 LLM 针对文档内容生成问答对
- 后台异步执行 RAG 管线 + Ragas 评分
- 查询评估任务与明细
"""
import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.evaluation import EvalRecord, EvalTask

logger = logging.getLogger(__name__)

# 样本文档目录
SAMPLES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "docs" / "data" / "samples"


def list_sample_docs() -> list[dict]:
    """扫描 docs/data/samples 目录，返回可选文档列表。"""
    if not SAMPLES_DIR.exists():
        return []
    docs = []
    for f in sorted(SAMPLES_DIR.iterdir()):
        if f.is_file() and f.suffix.lower() in (".txt", ".md", ".pdf", ".docx", ".xlsx"):
            docs.append({
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "file_type": f.suffix.lstrip(".").lower(),
            })
    return docs


async def generate_questions(file_names: list[str], num_per_doc: int = 3) -> list[dict]:
    """使用项目自身 LLM 对指定文档内容生成问答对。"""
    from langchain_openai import ChatOpenAI

    api_key = settings.dashscope_api_key
    base_url = settings.dashscope_base_url
    model = settings.llm_model or "qwen-plus"

    llm = ChatOpenAI(
        model=model,
        openai_api_key=api_key,
        openai_api_base=base_url,
        temperature=0.7,
    )

    all_questions: list[dict] = []
    for fname in file_names:
        fpath = SAMPLES_DIR / fname
        if not fpath.exists():
            logger.warning(f"文档不存在，跳过: {fname}")
            continue

        content = fpath.read_text(encoding="utf-8")
        # 截取前 4000 字符避免超长
        content_trimmed = content[:4000]

        prompt = f"""你是一位专业的产品知识质量评估专家。请根据以下文档内容，生成 {num_per_doc} 道问答题。

要求：
1. 问题应覆盖文档的不同章节和关键信息点
2. 问题要具体、可验证，不要过于笼统
3. 标准答案（ground_truth）必须完全基于文档内容，引用具体数据和事实
4. 严格按 JSON 数组格式输出，不要包含其他内容

文档内容：
---
{content_trimmed}
---

请输出 JSON 数组格式（不要 markdown 代码块包裹）：
[{{"question": "问题1", "ground_truth": "标准答案1"}}, ...]"""

        try:
            resp = await llm.ainvoke(prompt)
            text = resp.content.strip()
            # 清理可能的 markdown 代码块包裹
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            items = json.loads(text)
            if isinstance(items, list):
                for item in items:
                    if "question" in item and "ground_truth" in item:
                        all_questions.append({
                            "question": item["question"],
                            "ground_truth": item["ground_truth"],
                        })
            logger.info(f"✓ 文档 {fname} 成功生成 {len(items)} 道题目")
        except Exception as e:
            logger.error(f"✗ 文档 {fname} 出题失败: {e}")

    return all_questions


async def _run_evaluation_background(task_id: str, questions: list[dict]):
    """后台异步执行评估全流程：RAG 管线 → Ragas 评分 → 写数据库。"""
    from app.rag import reranker
    from app.rag.chain import build_chat_pipeline
    from app.rag.prompt import build_context
    from app.rag.retriever import retrieve

    async with async_session_maker() as db:
        task = await db.get(EvalTask, task_id)
        if not task:
            return

        try:
            total = len(questions)
            task.status = "evaluating"
            task.total_questions = total
            task.current_step = "正在运行 RAG 管线..."
            await db.commit()

            # 阶段 1: 逐题运行 RAG 管线
            records_data: list[dict] = []
            for idx, q_item in enumerate(questions, 1):
                question = q_item["question"]
                ground_truth = q_item["ground_truth"]

                task.progress = int((idx - 1) / total * 50)
                task.current_step = f"正在处理第 {idx}/{total} 题..."
                await db.commit()

                try:
                    hits = await retrieve(question, top_k=20)
                    if hits:
                        docs = [
                            (h.get("payload", {}).get("text") or h.get("payload", {}).get("chunk_content") or "")[:300]
                            for h in hits
                        ]
                        ranked = await reranker.rerank(question, docs, top_n=6)
                        reranked_hits = [hits[idx_r] for idx_r, _ in ranked]
                    else:
                        reranked_hits = []

                    retrieved_contexts = [
                        hit.get("payload", {}).get("text") or hit.get("payload", {}).get("chunk_content") or ""
                        for hit in reranked_hits
                    ]
                    context_str = build_context(reranked_hits)
                    pipeline = build_chat_pipeline()
                    response = await pipeline.ainvoke({
                        "context": context_str,
                        "question": question,
                        "history": [],
                    })
                    answer_text = response.content if hasattr(response, "content") else str(response)
                except Exception as e:
                    logger.error(f"RAG 管线处理问题失败: {e}")
                    answer_text = f"[处理失败: {e}]"
                    retrieved_contexts = []

                records_data.append({
                    "question": question,
                    "ground_truth": ground_truth,
                    "response": answer_text,
                    "retrieved_contexts": retrieved_contexts,
                })

            # 阶段 2: Ragas 评分
            task.progress = 55
            task.current_step = "正在执行 Ragas 量化评分..."
            await db.commit()

            scored_records = await _run_ragas_scoring(records_data)

            # 阶段 3: 写入明细记录
            task.progress = 90
            task.current_step = "正在保存评估结果..."
            await db.commit()

            sum_f = sum_ar = sum_cp = sum_cr = 0.0
            count = len(scored_records)

            for rec in scored_records:
                record = EvalRecord(
                    id=str(uuid.uuid4()),
                    task_id=task_id,
                    question=rec["question"],
                    ground_truth=rec["ground_truth"],
                    response=rec["response"],
                    retrieved_contexts=json.dumps(rec["retrieved_contexts"], ensure_ascii=False),
                    faithfulness=rec.get("faithfulness"),
                    answer_relevancy=rec.get("answer_relevancy"),
                    context_precision=rec.get("context_precision"),
                    context_recall=rec.get("context_recall"),
                )
                db.add(record)

                sum_f += rec.get("faithfulness") or 0
                sum_ar += rec.get("answer_relevancy") or 0
                sum_cp += rec.get("context_precision") or 0
                sum_cr += rec.get("context_recall") or 0

            # 计算平均分
            task.avg_faithfulness = round(sum_f / count, 4) if count else None
            task.avg_answer_relevancy = round(sum_ar / count, 4) if count else None
            task.avg_context_precision = round(sum_cp / count, 4) if count else None
            task.avg_context_recall = round(sum_cr / count, 4) if count else None
            task.status = "done"
            task.progress = 100
            task.current_step = "评估完成"
            task.finished_at = datetime.utcnow()
            await db.commit()
            logger.info(f"✓ 评估任务 {task_id} 完成，共 {count} 题")

        except Exception as e:
            logger.exception(f"评估任务 {task_id} 失败: {e}")
            task.status = "failed"
            task.error = str(e)
            task.current_step = f"评估失败: {e}"
            await db.commit()


async def _run_ragas_scoring(records_data: list[dict]) -> list[dict]:
    """调用 Ragas 对 RAG 管线结果进行量化评分。"""
    try:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI
        from ragas import evaluate
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from ragas.llms import LangchainLLMWrapper
        from ragas.metrics import answer_relevancy, context_precision, context_recall, faithfulness

        from app.rag.embedder import get_cached_embedder

        api_key = settings.dashscope_api_key
        base_url = settings.dashscope_base_url
        eval_model = settings.llm_model or "qwen-max"

        judge_llm = LangchainLLMWrapper(
            ChatOpenAI(model=eval_model, openai_api_key=api_key, openai_api_base=base_url, temperature=0.0)
        )
        judge_embeddings = LangchainEmbeddingsWrapper(get_cached_embedder())

        hf_dataset = Dataset.from_dict({
            "user_input": [r["question"] for r in records_data],
            "response": [r["response"] for r in records_data],
            "retrieved_contexts": [r["retrieved_contexts"] for r in records_data],
            "reference": [r["ground_truth"] for r in records_data],
        })

        results = evaluate(
            dataset=hf_dataset,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
            llm=judge_llm,
            embeddings=judge_embeddings,
        )

        df = results.to_pandas()
        for idx, rec in enumerate(records_data):
            if idx < len(df):
                row = df.iloc[idx]
                rec["faithfulness"] = float(row.get("faithfulness", 0) or 0)
                rec["answer_relevancy"] = float(row.get("answer_relevancy", 0) or 0)
                rec["context_precision"] = float(row.get("context_precision", 0) or 0)
                rec["context_recall"] = float(row.get("context_recall", 0) or 0)

    except Exception as e:
        logger.error(f"Ragas 评分失败: {e}")
        for rec in records_data:
            rec.setdefault("faithfulness", None)
            rec.setdefault("answer_relevancy", None)
            rec.setdefault("context_precision", None)
            rec.setdefault("context_recall", None)

    return records_data


async def create_and_run_task(questions: list[dict], source_files: list[str]) -> EvalTask:
    """创建评估任务并启动后台执行。"""
    async with async_session_maker() as db:
        task = EvalTask(
            id=str(uuid.uuid4()),
            status="pending",
            total_questions=len(questions),
            source_files=json.dumps(source_files, ensure_ascii=False),
            current_step="任务已创建，等待执行...",
        )
        db.add(task)
        await db.commit()
        await db.refresh(task)
        task_id = task.id

    # 后台执行（不阻塞请求返回）
    asyncio.create_task(_run_evaluation_background(task_id, questions))
    return task


async def get_task(db: AsyncSession, task_id: str) -> EvalTask | None:
    return await db.get(EvalTask, task_id)


async def list_tasks(db: AsyncSession) -> list[EvalTask]:
    result = await db.execute(select(EvalTask).order_by(EvalTask.created_at.desc()).limit(50))
    return list(result.scalars().all())


async def get_task_records(db: AsyncSession, task_id: str) -> list[EvalRecord]:
    result = await db.execute(
        select(EvalRecord).where(EvalRecord.task_id == task_id).order_by(EvalRecord.created_at)
    )
    return list(result.scalars().all())
