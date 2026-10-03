"""POST /tutor/explain: 提出コードから最小修正・ずれの解説・似た問題を返す。"""

import logging
import time
from dataclasses import asdict
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.routers.knowledge import _call_gemini, _gemini_client, _parse_json
from app.schemas.tutor import ExplainRequest, ExplainResponse
from app.services.editorial_chunker import get_problem_body_text
from app.services.tutor import TutorError, explain, load_problem

router = APIRouter(prefix="/tutor", tags=["tutor"])
logger = logging.getLogger(__name__)

# 修正案（LLM 1 回目）は精度の高い flash、それ以外と flash が使えないときは flash-lite
FIRST_PASS_MODEL = "gemini-2.5-flash"
DEFAULT_MODEL = "gemini-2.5-flash-lite"

# Gemini が混雑（503 UNAVAILABLE）のときに待つ秒数。要素数が再試行の回数
_BUSY_RETRY_WAITS = (2, 5, 10)


def _is_busy(e: HTTPException) -> bool:
    return e.status_code == 500 and ("503" in str(e.detail) or "UNAVAILABLE" in str(e.detail))


def _is_quota_exceeded(e: HTTPException) -> bool:
    return e.status_code == 429


def _call_with_retry(client, prompt: str, schema: dict, model: str = DEFAULT_MODEL) -> str:
    for wait in (*_BUSY_RETRY_WAITS, None):
        try:
            return _call_gemini(client, prompt, schema, model)
        except HTTPException as e:
            if not _is_busy(e):
                raise
            if wait is None:
                raise HTTPException(status_code=503, detail="Gemini が混雑しています。少し時間をおいて再度お試しください。")
            logger.warning("Gemini が混雑しているため %d 秒後に再試行します", wait)
            time.sleep(wait)


def _call_first_pass(client, prompt: str, schema: dict) -> str:
    """flash を 1 回試し、混雑・クォータ超過なら flash-lite（混雑時は再試行あり）に切り替える。"""
    try:
        return _call_gemini(client, prompt, schema, FIRST_PASS_MODEL)
    except HTTPException as e:
        if not (_is_busy(e) or _is_quota_exceeded(e)):
            raise
        logger.warning("%s が使えないため %s に切り替えます: %s", FIRST_PASS_MODEL, DEFAULT_MODEL, e.detail)
    return _call_with_retry(client, prompt, schema, DEFAULT_MODEL)


@lru_cache(maxsize=1)
def _vector_store():
    # 埋め込みモデルの読み込みに時間がかかるため、プロセス内で使い回す
    from app.services.vector_store import EditorialVectorStore

    return EditorialVectorStore()


def _searcher():
    try:
        return _vector_store()
    except Exception:
        # 検索なしでも解説は返せるので止めない（レスポンスの warnings にも出る）
        logger.exception("公式解説ストアを開けませんでした")
        return None


@router.post("/explain", response_model=ExplainResponse)
def explain_submission(req: ExplainRequest, db: Session = Depends(get_db)):
    problem = load_problem(req.problem_id)
    if problem is None:
        raise HTTPException(
            status_code=404,
            detail=f"{req.problem_id} の問題データがありません。"
                   "scripts/build_editorial_index.py で取得済みの問題（ABC の C・D）を指定してください。",
        )

    client = _gemini_client()

    def generate(prompt: str, schema: dict) -> dict:
        return _parse_json(_call_with_retry(client, prompt, schema))

    def generate_first(prompt: str, schema: dict) -> dict:
        return _parse_json(_call_first_pass(client, prompt, schema))

    try:
        result = explain(
            db,
            generate,
            _searcher(),
            problem,
            req.code,
            req.verdict,
            body_text=get_problem_body_text(req.problem_id),
            username=req.username,
            generate_first=generate_first,
        )
    except TutorError as e:
        raise HTTPException(status_code=502, detail=str(e))

    log = result.log
    return ExplainResponse(
        log_id=log.id,
        created_at=log.created_at,
        problem_id=log.problem_id,
        verdict=log.verdict,
        original_code=log.original_code,
        fixed_code=log.fixed_code,
        diff=log.diff,
        diff_lines=log.diff_lines,
        total_lines=result.total_lines,
        mistake_level=log.mistake_level,
        mistake_type=log.mistake_type,
        samples_passed=log.samples_passed,
        sample_cases=[asdict(c) for c in result.sample_cases],
        attempts=result.attempts,
        gap_summary=log.gap_summary,
        correct_idea=log.correct_idea,
        lesson=log.lesson,
        past_same_type_count=result.past_same_type_count,
        explanation=result.explanation,
        reference=[asdict(p) for p in result.reference],
        next_problems=[asdict(p) for p in result.next_problems],
        warnings=result.warnings,
    )
