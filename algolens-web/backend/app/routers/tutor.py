"""POST /tutor/explain: 提出コードから最小修正・ずれの解説・似た問題を返す。
POST /tutor/logs/{log_id}/submit-result: 修正版を提出した結果を記録し、AC 以外なら作り直す。
"""

import logging
import time
from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.routers.knowledge import _call_gemini, _gemini_client, _parse_json
from app.models.mistake_log import FIX_CONFIRMED, MistakeLog
from app.schemas.tutor import ExplainRequest, ExplainResponse, SubmitResultRequest, SubmitResultResponse
from app.services.contests import UNKNOWN_MESSAGE, find_contest, finished_error
from app.services.editorial_chunker import get_problem_body_text
from app.services.review import tutor_result_to_dict, update_report_after_submit
from app.services.tutor import Generate, TutorError, explain, load_problem, record_submit_result

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


def gemini_generators(client) -> tuple[Generate, Generate]:
    """(通常の呼び出し, 修正案用の呼び出し) を返す。どちらも解析済みの JSON を返す。"""

    def generate(prompt: str, schema: dict) -> dict:
        return _parse_json(_call_with_retry(client, prompt, schema))

    def generate_first(prompt: str, schema: dict) -> dict:
        return _parse_json(_call_first_pass(client, prompt, schema))

    return generate, generate_first


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

    # AtCoder の生成 AI の利用ルールのため、コンテスト終了前は使わない
    try:
        error = finished_error(find_contest(problem.contest_id))
    except httpx.HTTPError:
        error = UNKNOWN_MESSAGE
    if error:
        raise HTTPException(status_code=403, detail=error)

    generate, generate_first = gemini_generators(_gemini_client())
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
    return ExplainResponse(**tutor_result_to_dict(result))


@router.post("/logs/{log_id}/submit-result", response_model=SubmitResultResponse)
def submit_result(log_id: int, req: SubmitResultRequest, db: Session = Depends(get_db)):
    """修正版を提出した結果を記録する。AC 以外なら、その結果を伝えて修正版を作り直す。"""
    log = db.get(MistakeLog, log_id)
    if log is None:
        raise HTTPException(status_code=404, detail=f"記録 {log_id} がありません")
    try:
        record_submit_result(db, log, req.verdict)
    except TutorError as e:
        raise HTTPException(status_code=409, detail=str(e))

    if log.fix_status == FIX_CONFIRMED:
        update_report_after_submit(db, log, None)
        return SubmitResultResponse(
            log_id=log.id, fix_status=log.fix_status, submitted_verdict=log.submitted_verdict, result=None
        )

    problem = load_problem(log.problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail=f"{log.problem_id} の問題データがありません")
    generate, generate_first = gemini_generators(_gemini_client())
    try:
        result = explain(
            db,
            generate,
            _searcher(),
            problem,
            log.original_code,
            log.verdict,
            body_text=get_problem_body_text(log.problem_id),
            username=req.username,
            generate_first=generate_first,
            retry_of=log,
        )
    except TutorError as e:
        # 提出結果（修正失敗）は記録済み。同じ結果を選び直すと作り直しだけやり直せる
        raise HTTPException(status_code=502, detail=f"提出結果は記録しましたが、作り直しに失敗しました: {e}")
    payload = tutor_result_to_dict(result)
    update_report_after_submit(db, log, payload)
    return SubmitResultResponse(
        log_id=log.id, fix_status=log.fix_status, submitted_verdict=log.submitted_verdict,
        result=ExplainResponse(**payload),
    )
