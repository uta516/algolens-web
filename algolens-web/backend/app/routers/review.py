"""振り返り: 直近のコンテストの提出を取り込み、問題ごとに家庭教師の結果を作って保存する。

Streamlit から次の順に呼ぶ:
  GET  /review/contests?username=     取り込めるコンテスト（直近の ABC で提出があるもの）
  POST /review/import                  最後の提出ごとに pending の行を作る
  POST /review/process/{report_id}     1 問処理して保存（これを pending の数だけ順番に呼ぶ）
  GET  /review/reports                 保存済みの結果
"""

import json
import threading
import time
from functools import lru_cache

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tutor_report import REPORT_DONE, TutorReport
from app.routers.knowledge import _gemini_client
from app.routers.tutor import _searcher, gemini_generators
from app.schemas.review import ContestOut, ImportRequest, ReportOut, ReportSummary, SavedContestOut
from app.services.atcoder_fetcher import fetch_problems, fetch_user_submissions
from app.services.editorial_chunker import get_problem_body_text
from app.services.editorial_index import index_problem
from app.services.editorial_scraper import AtCoderClient
from app.services.review import (
    ReviewDeps,
    ReviewError,
    fetch_submission_code,
    latest_reports,
    plan_contest,
    prepare_problem_data,
    problem_index_of,
    process_report,
)
from app.services.tutor import TutorError

router = APIRouter(prefix="/review", tags=["review"])

_RECENT_CONTESTS = 10
_CACHE_TTL_SEC = 3600
_cache: dict[str, tuple[float, object]] = {}
# Gemini と AtCoder へのアクセスを 1 問ずつ順番に行うためのロック
_process_lock = threading.Lock()


def _cached(key: str, fetch):
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL_SEC:
        return hit[1]
    value = fetch()
    _cache[key] = (time.time(), value)
    return value


def _fetch_contests() -> list[dict]:
    resp = httpx.get("https://kenkoooo.com/atcoder/resources/contests.json", timeout=60)
    resp.raise_for_status()
    return resp.json()


def _recent_abc_contests(limit: int = _RECENT_CONTESTS) -> list[dict]:
    """終了済みの ABC を新しい順に limit 件。"""
    now = time.time()
    abcs = [
        c for c in _cached("contests", _fetch_contests)
        if c["id"].startswith("abc") and c["start_epoch_second"] + c.get("duration_second", 0) <= now
    ]
    return sorted(abcs, key=lambda c: c["start_epoch_second"], reverse=True)[:limit]


def _problem_titles(contest_id: str) -> dict[str, str]:
    """problem_id → "C. 問題名"（AtCoder Problems の問題一覧から）。"""
    titles = {}
    for p in _cached("problems", fetch_problems):
        if p.get("contest_id") == contest_id:
            titles[p["id"]] = f"{problem_index_of(p['id'])}. {p.get('name', '')}".rstrip(". ")
    return titles


@lru_cache(maxsize=1)
def _atcoder_client() -> AtCoderClient:
    # プロセス内で 1 つを使い回し、AtCoder へのアクセス間隔（1.5 秒）を問題をまたいで守る
    return AtCoderClient(interval=1.5)


def _summary(r: TutorReport) -> ReportSummary:
    return ReportSummary(
        id=r.id, contest_id=r.contest_id, problem_id=r.problem_id, problem_index=r.problem_index,
        title=r.title, submission_id=r.submission_id, verdict=r.verdict, language=r.language,
        wa_count=r.wa_count, status=r.status, kind=r.kind, editorial_available=r.editorial_available,
        gemini_calls=r.gemini_calls, error=r.error,
    )


@router.get("/contests", response_model=list[ContestOut])
def list_contests(username: str):
    """直近の ABC のうち、ユーザーの提出があるものを新しい順に返す。"""
    contests = _recent_abc_contests()
    if not contests:
        return []
    try:
        subs = fetch_user_submissions(username, from_second=contests[-1]["start_epoch_second"])
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"AtCoder Problems API から提出を取得できませんでした: {e}")
    counts: dict[str, int] = {}
    for s in subs:
        counts[s["contest_id"]] = counts.get(s["contest_id"], 0) + 1
    return [
        ContestOut(contest_id=c["id"], title=c.get("title", c["id"]),
                   start_epoch_second=c["start_epoch_second"], submission_count=counts[c["id"]])
        for c in contests if counts.get(c["id"])
    ]


@router.post("/import", response_model=list[ReportSummary])
def import_contest(req: ImportRequest, db: Session = Depends(get_db)):
    """コンテストの提出を取得し、問題ごとの最後の提出について pending の行を作る（既にあれば作らない）。"""
    contest = next((c for c in _cached("contests", _fetch_contests) if c["id"] == req.contest_id), None)
    if contest is None:
        raise HTTPException(status_code=404, detail=f"コンテスト {req.contest_id} が見つかりません")
    try:
        subs = fetch_user_submissions(req.username, from_second=contest["start_epoch_second"])
        titles = _problem_titles(req.contest_id)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"AtCoder Problems API から取得できませんでした: {e}")
    reports = plan_contest(db, req.username, req.contest_id, subs, titles)
    if not reports:
        raise HTTPException(status_code=404, detail=f"{req.username} の {req.contest_id} への提出が見つかりません")
    return [_summary(r) for r in reports]


@router.post("/process/{report_id}", response_model=ReportSummary)
def process_one(report_id: int, db: Session = Depends(get_db)):
    """1 問処理して保存する。処理済みならそのまま返す。"""
    report = db.get(TutorReport, report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="結果が見つかりません")
    if report.status == REPORT_DONE:
        return _summary(report)
    if not _process_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="別の問題を処理中です。終わるまで待ってください。")
    try:
        client = _atcoder_client()
        store = _searcher()

        def index_editorials(problem_id: str) -> None:
            if store is not None and not store.has_problem(problem_id):
                index_problem(store, problem_id)

        generate, generate_first = gemini_generators(_gemini_client())
        deps = ReviewDeps(
            generate=generate,
            generate_first=generate_first,
            searcher=store,
            fetch_code=lambda contest_id, sid: fetch_submission_code(client, contest_id, sid),
            prepare_problem=lambda r: prepare_problem_data(client, r, index_editorials),
            body_text=get_problem_body_text,
        )
        process_report(db, report, deps)
    except HTTPException:
        raise
    except (ReviewError, TutorError) as e:
        raise HTTPException(status_code=502, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"AtCoder から取得できませんでした: {e}")
    finally:
        _process_lock.release()
    return _summary(report)


@router.get("/reports", response_model=list[ReportOut])
def list_reports(username: str, contest_id: str, db: Session = Depends(get_db)):
    """保存済みの結果（問題ごとに最後の提出の分）を問題順に返す。"""
    return [
        ReportOut(
            **_summary(r).model_dump(),
            original_code=r.original_code,
            payload=json.loads(r.payload) if r.payload else None,
        )
        for r in latest_reports(db, username, contest_id)
    ]


@router.get("/saved-contests", response_model=list[SavedContestOut])
def list_saved_contests(username: str, db: Session = Depends(get_db)):
    """保存済みの結果があるコンテストを新しい順に返す。"""
    contest_ids = db.scalars(
        select(TutorReport.contest_id).where(TutorReport.username == username).distinct()
    ).all()
    out = []
    for cid in contest_ids:
        reports = latest_reports(db, username, cid)
        out.append(SavedContestOut(
            contest_id=cid,
            problem_count=len(reports),
            done_count=sum(r.status == REPORT_DONE for r in reports),
        ))
    # "abc99" と "abc100" を正しく並べるため数字部分で比べる
    return sorted(out, key=lambda c: int(c.contest_id[3:] or 0), reverse=True)
