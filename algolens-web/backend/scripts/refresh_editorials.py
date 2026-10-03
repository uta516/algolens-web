"""取り込み時には公式解説が未公開だった問題について、解説を取り直して解説ストアに追加登録する。

対象は data/editorials/ のうち、meta.json の解説一覧が空の問題（--problem で個別指定も可）。

実行方法（backend/ ディレクトリから）:
    python scripts/refresh_editorials.py                       # 解説がない問題をすべて確認
    python scripts/refresh_editorials.py --contest abc420      # コンテストを絞る
    python scripts/refresh_editorials.py --problem abc420_c    # 1 問だけ
    python scripts/refresh_editorials.py --dry-run             # 対象の一覧だけ表示
"""

import argparse
import os
import sys

import httpx

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
os.chdir(_backend_dir)          # backend/.env の CHROMA_DIR を読むため
sys.path.insert(0, _backend_dir)

from app.services.editorial_index import index_problem  # noqa: E402
from app.services.editorial_scraper import EDITORIALS_DIR, AtCoderClient, load_meta, refresh_editorials  # noqa: E402
from app.services.vector_store import EditorialVectorStore  # noqa: E402


def find_targets(contest: str | None) -> list[str]:
    targets = []
    for pdir in sorted(EDITORIALS_DIR.iterdir()):
        meta = load_meta(pdir.name)
        if meta is None or meta["editorials"]:
            continue
        if contest and meta.get("contest_id") != contest:
            continue
        targets.append(pdir.name)
    return targets


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--contest", help="対象のコンテスト ID（例: abc420）")
    parser.add_argument("--problem", action="append", help="対象の問題 ID（複数指定可）")
    parser.add_argument("--interval", type=float, default=1.5, help="AtCoder へのアクセス間隔（秒, 1〜2）")
    parser.add_argument("--dry-run", action="store_true", help="対象を表示するだけで取得しない")
    args = parser.parse_args()

    if not 1.0 <= args.interval <= 2.0:
        parser.error("--interval は 1〜2 秒で指定してください")

    targets = args.problem or find_targets(args.contest)
    print(f"対象: {len(targets)} 問")
    if args.dry_run or not targets:
        for pid in targets:
            print(f"  {pid}")
        return

    client = AtCoderClient(interval=args.interval)
    store = EditorialVectorStore()
    added = still_missing = failed = 0
    try:
        for i, pid in enumerate(targets, 1):
            try:
                editorials = refresh_editorials(client, pid)
            except (httpx.HTTPError, FileNotFoundError) as e:
                failed += 1
                print(f"[{i}/{len(targets)}] {pid}: 取得失敗 ({e})")
                continue
            if not editorials:
                still_missing += 1
                print(f"[{i}/{len(targets)}] {pid}: まだ公式解説がありません")
                continue
            n_chunks = index_problem(store, pid)
            added += 1
            print(f"[{i}/{len(targets)}] {pid}: 解説 {len(editorials)} 件を登録 ({n_chunks} チャンク)")
    finally:
        client.close()
    print(f"追加登録={added} 未公開のまま={still_missing} 失敗={failed}")


if __name__ == "__main__":
    main()
