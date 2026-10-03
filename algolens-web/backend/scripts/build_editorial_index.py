"""ABC の C・D 問題（難易度 1200 未満）の公式解説を取得し、ChromaDB に登録するバッチ。

実行方法（backend/ ディレクトリから）:
    python scripts/build_editorial_index.py              # 取得 → 登録（どちらも済みのものはスキップ）
    python scripts/build_editorial_index.py --limit 5    # 動作確認用に先頭 5 問だけ
    python scripts/build_editorial_index.py --skip-fetch # 保存済みの生データから登録だけ行う
    python scripts/build_editorial_index.py --reindex    # 登録済みの問題も分割・埋め込みし直す

ChromaDB の保存先は環境変数 CHROMA_DIR（未設定なら backend/data/chroma/）。
"""

import argparse
import os
import sys

import httpx

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
os.chdir(_backend_dir)          # SQLite の相対パス "sqlite:///./data/..." を解決
sys.path.insert(0, _backend_dir)

from app.core.database import SessionLocal  # noqa: E402
from app.models.problem import Problem  # noqa: E402
from app.services.atcoder_fetcher import fetch_problem_models, fetch_problems  # noqa: E402
from app.services.editorial_index import index_problem  # noqa: E402
from app.services.editorial_scraper import (  # noqa: E402
    EDITORIALS_DIR,
    AtCoderClient,
    fetch_and_save_problem,
    load_meta,
    select_target_problems,
)
from app.services.vector_store import EditorialVectorStore, resolve_chroma_dir  # noqa: E402


def fetch_contest_problems() -> list[dict]:
    """コンテストと問題の対応表（1 問が ABC と ADT の両方に属する場合も全て含む）。"""
    resp = httpx.get("https://kenkoooo.com/atcoder/resources/contest-problem.json", timeout=60)
    resp.raise_for_status()
    return resp.json()


def load_tags_from_db() -> dict[str, str]:
    """DB の problems.tags（推測タグ）を problem_id → "tag1,tag2" で返す。

    DB の atcoder_problem_id は "{contest_id}_{problem_id}"（例: abc001_abc001_3）なので、
    先頭の contest_id を外して AtCoder の problem_id に合わせる。
    """
    db = SessionLocal()
    try:
        rows = db.query(Problem.atcoder_problem_id, Problem.contest_id, Problem.tags).all()
    finally:
        db.close()
    tags = {}
    for pid, contest_id, value in rows:
        prefix = f"{contest_id}_"
        key = pid[len(prefix):] if pid.startswith(prefix + contest_id) else pid
        tags[key] = value or ""
    return tags


def fetch_all(targets, interval: float) -> None:
    client = AtCoderClient(interval=interval)
    fetched = skipped = failed = 0
    try:
        for i, problem in enumerate(targets, 1):
            try:
                if fetch_and_save_problem(client, problem, EDITORIALS_DIR):
                    fetched += 1
                    meta = load_meta(problem.problem_id)
                    print(f"[{i}/{len(targets)}] {problem.problem_id}: "
                          f"samples={meta['sample_count']} editorials={len(meta['editorials'])}")
                else:
                    skipped += 1
            except httpx.HTTPError as e:
                # meta.json を書かないので、次回実行時に取り直される
                failed += 1
                print(f"[{i}/{len(targets)}] {problem.problem_id}: 取得失敗 ({e})")
    finally:
        client.close()
    print(f"取得: 新規={fetched} スキップ={skipped} 失敗={failed}")


def index_all(targets, reindex: bool) -> None:
    store = EditorialVectorStore()
    indexed = skipped = no_editorial = 0
    for problem in targets:
        meta = load_meta(problem.problem_id)
        if meta is None:
            continue
        if not meta["editorials"]:
            no_editorial += 1
            continue
        if not reindex and store.has_problem(problem.problem_id):
            skipped += 1
            continue

        n_chunks = index_problem(store, problem.problem_id)
        indexed += 1
        print(f"登録: {problem.problem_id} ({n_chunks} チャンク)")
    print(f"登録: 新規={indexed} スキップ={skipped} 公式テキスト解説なし={no_editorial} "
          f"総チャンク数={store.count()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limit", type=int, default=None, help="処理する問題数の上限")
    parser.add_argument("--interval", type=float, default=1.5, help="AtCoder へのアクセス間隔（秒, 1〜2）")
    parser.add_argument("--skip-fetch", action="store_true", help="取得を行わず登録だけ行う")
    parser.add_argument("--skip-index", action="store_true", help="取得だけ行い登録しない")
    parser.add_argument("--reindex", action="store_true", help="登録済みの問題も登録し直す")
    args = parser.parse_args()

    if not 1.0 <= args.interval <= 2.0:
        parser.error("--interval は 1〜2 秒で指定してください")

    print("対象問題を選定中（AtCoder Problems API）...")
    targets = select_target_problems(
        fetch_contest_problems(), fetch_problems(), fetch_problem_models(), load_tags_from_db()
    )
    if args.limit is not None:
        targets = targets[: args.limit]
    print(f"対象: {len(targets)} 問  生データ: {EDITORIALS_DIR}  ChromaDB: {resolve_chroma_dir()}")

    if not args.skip_fetch:
        fetch_all(targets, args.interval)
    if not args.skip_index:
        index_all(targets, args.reindex)


if __name__ == "__main__":
    main()
