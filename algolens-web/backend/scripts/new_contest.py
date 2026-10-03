"""コンテスト用のファイルを作る。

submissions/<contest_id>/ に、問題ごとの a.py（解答）と a.txt（入力例・出力例を貼る）を作る。
すでにあるファイルは上書きしない。問題文は入れない。

実行方法（どこからでも）:
    python scripts/new_contest.py abc477            # A〜D
    python scripts/new_contest.py abc477 --upto e   # A〜E

置き場所は SUBMISSIONS_DIR（未設定なら AtCorder/submissions/）。
"""

import argparse
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
os.chdir(_backend_dir)          # backend/.env の SUBMISSIONS_DIR を読むため
sys.path.insert(0, _backend_dir)

from app.services.workspace import DEFAULT_UPTO, create_contest_files, resolve_submissions_dir  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("contest_id", help="コンテストID（例: abc477）")
    parser.add_argument("--upto", default=DEFAULT_UPTO, help="どの問題まで作るか（例: e。既定は d）")
    args = parser.parse_args()

    base = resolve_submissions_dir()
    try:
        results = create_contest_files(base, args.contest_id, args.upto)
    except ValueError as e:
        parser.error(str(e))

    for path, created in results:
        print(f"{'作成' if created else 'あり（そのまま）'}: {path}")
    print(f"\n{sum(c for _, c in results)} 個作成しました（フォルダ: {results[0][0].parent}）")


if __name__ == "__main__":
    main()
