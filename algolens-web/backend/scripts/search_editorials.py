"""公式解説ストアの動作確認用: 文章を入れると似た解説を上位 10 問（1 問 1 チャンク）表示する。

コードと証明のチャンクは検索対象外。--body のときは指定した問題自身を結果から外す。

実行方法（backend/ ディレクトリから）:
    python scripts/search_editorials.py "区間の和を高速に求めたい"
    python scripts/search_editorials.py --body abc300_c   # 本問の解説本文をクエリにする
"""

import argparse
import os
import sys

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
os.chdir(_backend_dir)          # backend/.env の CHROMA_DIR を読むため
sys.path.insert(0, _backend_dir)

from app.services.editorial_chunker import get_problem_body_text  # noqa: E402
from app.services.vector_store import EditorialVectorStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query", nargs="?", help="検索する文章")
    parser.add_argument("--body", metavar="PROBLEM_ID", help="指定した問題の解説本文をクエリにする")
    parser.add_argument("-k", type=int, default=10)
    args = parser.parse_args()

    if args.body:
        query = get_problem_body_text(args.body)
        if not query:
            parser.error(f"{args.body} の解説本文が見つかりません")
    elif args.query:
        query = args.query
    else:
        parser.error("query か --body を指定してください")

    print(f"クエリ: {query[:100]}{'...' if len(query) > 100 else ''}\n")
    exclude = [args.body] if args.body else []
    results = EditorialVectorStore().search(query, k=args.k, exclude_problem_ids=exclude)
    for rank, r in enumerate(results, 1):
        m = r.metadata
        preview = r.text.replace("\n", " ")[:80]
        print(f"{rank:2d}. [{r.score:.3f}] {m['problem_id']} ({m.get('difficulty', '?')}) "
              f"{m['section']}/{m['editorial_type']}  {preview}")


if __name__ == "__main__":
    main()
