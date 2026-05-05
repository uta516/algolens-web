"""hiyokosann 専用 AtCoder データ一括同期スクリプト。

実行方法（backend/ ディレクトリから）:
    python scripts/sync_atcoder_data.py
"""

import os
import sys
from datetime import datetime

import httpx

# backend/ を sys.path に追加（どこから実行しても動くように）
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
os.chdir(_backend_dir)          # SQLite の相対パス "sqlite:///./data/..." を解決
sys.path.insert(0, _backend_dir)

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.models.problem import Problem  # noqa: E402
from app.models.submission import Submission  # noqa: E402
from app.models.user import User  # noqa: E402

Base.metadata.create_all(bind=engine)

TARGET_USER = "hiyokosann"
BASE = "https://kenkoooo.com/atcoder"
HEADERS = {"User-Agent": "AlgoLens/0.1 (github.com/uta516/algolens-web)"}


def fetch_json(url: str, params: dict | None = None):
    with httpx.Client(headers=HEADERS, timeout=60) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Step 1: 問題マスタ + 難易度
# ---------------------------------------------------------------------------

def sync_problems(db) -> tuple[int, int]:
    print("[1/3] merged-problems.json と problem-models.json を取得中...")
    problems_raw = fetch_json(f"{BASE}/resources/merged-problems.json")
    models_raw = fetch_json(f"{BASE}/resources/problem-models.json")
    print(f"      問題数: {len(problems_raw):,}  難易度モデル数: {len(models_raw):,}")

    inserted = updated = 0
    for p in problems_raw:
        pid = f"{p['contest_id']}_{p['id']}".lower()
        difficulty = models_raw.get(p["id"], {}).get("difficulty")
        problem_index = p.get("problem_index") or p["id"][-1]

        existing = db.query(Problem).filter(Problem.atcoder_problem_id == pid).first()
        if existing:
            existing.difficulty = difficulty
            existing.title = p.get("title", existing.title)
            existing.problem_index = str(problem_index).upper()
            updated += 1
        else:
            db.add(Problem(
                atcoder_problem_id=pid,
                contest_id=p["contest_id"].lower(),
                problem_index=str(problem_index).upper(),
                title=p.get("title", ""),
                difficulty=difficulty,
                url=f"https://atcoder.jp/contests/{p['contest_id']}/tasks/{p['id']}",
            ))
            inserted += 1

    db.commit()
    print(f"      → inserted={inserted:,}  updated={updated:,}")
    return inserted, updated


# ---------------------------------------------------------------------------
# Step 2: ユーザー登録
# ---------------------------------------------------------------------------

def ensure_user(db) -> User:
    print(f"[2/3] ユーザー '{TARGET_USER}' を確認中...")
    user = db.query(User).filter(User.atcoder_username == TARGET_USER).first()
    if not user:
        user = User(atcoder_username=TARGET_USER)
        db.add(user)
        db.commit()
        db.refresh(user)
        print(f"      → 新規作成しました (id={user.id})")
    else:
        print(f"      → 既存 (id={user.id})")
    return user


# ---------------------------------------------------------------------------
# Step 3: 提出データ
# ---------------------------------------------------------------------------

def sync_submissions(db, user: User) -> tuple[int, int]:
    print(f"[3/3] {TARGET_USER} の提出データを取得中...")
    raw_subs = fetch_json(
        f"{BASE}/atcoder-api/v3/user/submissions",
        params={"user": TARGET_USER, "from_second": 0},
    )
    print(f"      取得件数: {len(raw_subs):,}")

    inserted = skipped = 0
    for raw in raw_subs:
        atcoder_sid = raw.get("id")
        if atcoder_sid and db.query(Submission).filter(
            Submission.atcoder_submission_id == atcoder_sid
        ).first():
            skipped += 1
            continue

        pid_str = f"{raw['contest_id']}_{raw['problem_id']}".lower()
        problem = db.query(Problem).filter(Problem.atcoder_problem_id == pid_str).first()
        if not problem:
            skipped += 1
            continue

        db.add(Submission(
            user_id=user.id,
            problem_id=problem.id,
            atcoder_submission_id=atcoder_sid,
            status=raw.get("result", ""),
            language=raw.get("language"),
            execution_time_ms=raw.get("execution_time"),
            memory_kb=raw.get("memory"),
            score=raw.get("point"),
            submitted_at=datetime.utcfromtimestamp(raw["epoch_second"]),
        ))
        inserted += 1

    db.commit()
    print(f"      → inserted={inserted:,}  skipped={skipped:,}")
    return inserted, skipped


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 50)
    print(f"AtCorder データ同期: {TARGET_USER}")
    print("=" * 50)

    with SessionLocal() as db:
        sync_problems(db)
        user = ensure_user(db)
        sync_submissions(db, user)

    print("\n[DONE] 同期完了!")
