"""AtCoder Problems API からデータを同期するエンドポイント。"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.services.atcoder_fetcher import (
    fetch_problem_models,
    fetch_problem_tags,
    fetch_problems,
    fetch_user_submissions,
    normalize_submission,
)

router = APIRouter(prefix="/sync", tags=["sync"])

# ---------------------------------------------------------------------------
# タグ推定ヘルパー（シードデータ）
# ---------------------------------------------------------------------------

# タイトルキーワード → タグのマッピング（大文字小文字無視）
_TITLE_TAG_MAP: list[tuple[list[str], str]] = [
    (["binary search", "二分探索", "bisect"],        "二分探索"),
    (["bfs", "shortest path", "dijkstra", "最短経路"], "グラフ"),
    (["dfs", "depth", "tree", "木"],                 "DFS"),
    (["dp", "knapsack", "ナップサック", "部分和", "subsequence", "memoiz"], "DP"),
    (["cumulative", "prefix sum", "累積和"],           "累積和"),
    (["sort", "ソート"],                              "ソート"),
    (["greedy", "貪欲"],                              "グリーディ"),
    (["prime", "gcd", "lcm", "mod", "素数", "数学"],  "数学"),
    (["brute", "全探索", "enumerat", "exhaustive"],   "全探索"),
    (["bit", "bitmask", "subset"],                    "bit全探索"),
    (["stack", "queue", "スタック", "キュー"],         "データ構造"),
    (["segment tree", "fenwick", "bit tree", "セグ木"], "データ構造"),
    (["string", "文字列", "palindrome"],              "文字列"),
    (["grid", "matrix", "グリッド"],                  "グリッド"),
    (["graph", "グラフ", "edge", "vertex"],           "グラフ"),
]


def _infer_tags_from_title(title: str) -> list[str]:
    t = title.lower()
    return [tag for keywords, tag in _TITLE_TAG_MAP if any(kw.lower() in t for kw in keywords)]


def _seed_tags_by_difficulty(difficulty: float | None) -> list[str]:
    if difficulty is None:
        return ["実装"]
    if difficulty < 400:
        return ["実装", "全探索"]
    if difficulty < 800:
        return ["全探索", "ソート"]
    if difficulty < 1200:
        return ["二分探索", "累積和"]
    if difficulty < 1600:
        return ["DP", "グラフ"]
    if difficulty < 2000:
        return ["DP", "グラフ", "数学"]
    return ["数学", "データ構造"]


@router.post("/problems")
def sync_problems(db: Session = Depends(get_db)):
    """問題マスタと難易度データを一括取得してDBに保存する。"""
    problems_raw = fetch_problems()
    models_raw = fetch_problem_models()

    upserted = 0
    for p in problems_raw:
        pid = f"{p['contest_id']}_{p['id']}".lower()
        difficulty = models_raw.get(p["id"], {}).get("difficulty")

        existing = db.query(Problem).filter(Problem.atcoder_problem_id == pid).first()
        if existing:
            existing.difficulty = difficulty
            existing.title = p.get("title", existing.title)
        else:
            db.add(
                Problem(
                    atcoder_problem_id=pid,
                    contest_id=p["contest_id"].lower(),
                    problem_index=p["id"][-1].upper(),
                    title=p.get("title", ""),
                    difficulty=difficulty,
                    url=f"https://atcoder.jp/contests/{p['contest_id']}/tasks/{p['id']}",
                )
            )
            upserted += 1

    db.commit()
    return {"upserted": upserted, "total": len(problems_raw)}


@router.post("/tags")
def sync_tags(db: Session = Depends(get_db)):
    """問題タグを同期する。
    1. AtCoder Problems の problem-tags.json から取得を試みる。
    2. 取得できなかった・タグ未設定の問題には、タイトルキーワードと難易度からシードタグを付与する。
    """
    tags_map = fetch_problem_tags()
    api_updated = 0
    seed_updated = 0

    # --- API タグを適用 ---
    if tags_map:
        problems = db.query(Problem).filter(
            Problem.atcoder_problem_id.in_(list(tags_map.keys()))
        ).all()
        for p in problems:
            new_tags = tags_map.get(p.atcoder_problem_id, [])
            if new_tags:
                p.tags = ",".join(new_tags)
                api_updated += 1
        db.commit()

    # --- シードタグをタグ未設定の問題に付与 ---
    untagged = db.query(Problem).filter(Problem.tags == None).all()  # noqa: E711
    for p in untagged:
        title_tags = _infer_tags_from_title(p.title)
        diff_tags = _seed_tags_by_difficulty(p.difficulty)
        merged = list(dict.fromkeys(title_tags + diff_tags))[:3]
        if merged:
            p.tags = ",".join(merged)
            seed_updated += 1
    db.commit()

    return {
        "api_source": bool(tags_map),
        "api_updated": api_updated,
        "seed_updated": seed_updated,
        "total_tagged": db.query(Problem).filter(Problem.tags != None).count(),  # noqa: E711
    }


@router.post("/submissions/{username}")
def sync_submissions(username: str, from_second: int = 0, db: Session = Depends(get_db)):
    """指定ユーザーの提出データを取得してDBに保存する。"""
    user = db.query(User).filter(User.atcoder_username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Register the user first.")

    raw_subs = fetch_user_submissions(username, from_second=from_second)

    inserted = skipped = 0
    for raw in raw_subs:
        normalized = normalize_submission(raw)
        atcoder_sid = normalized["atcoder_submission_id"]

        if atcoder_sid and db.query(Submission).filter(
            Submission.atcoder_submission_id == atcoder_sid
        ).first():
            skipped += 1
            continue

        pid_str = normalized.pop("_atcoder_problem_id")
        problem = db.query(Problem).filter(Problem.atcoder_problem_id == pid_str).first()
        if not problem:
            skipped += 1
            continue

        db.add(Submission(user_id=user.id, problem_id=problem.id, **normalized))
        inserted += 1

    db.commit()
    return {"inserted": inserted, "skipped": skipped}
