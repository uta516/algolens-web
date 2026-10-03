"""サンプルを試す: c.txt の入力を c.py に渡して実行し、出力例と比べる（1 ケース 2 秒で打ち切り）。

実行方法（どこからでも）:
    python scripts/test.py abc477 c
    python scripts/test.py --file path/to/submissions/abc477/c.py   # c.txt でもよい（VS Code のタスク用）

c.txt がすべて空のとき:
  - 終了済みのコンテストなら、保存済みのサンプル（なければ問題ページ）を使う
  - コンテスト中は問題ページを自動で取得しない（c.txt に貼ってから試す）
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from pathlib import Path

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.dirname(_scripts_dir)
sys.path.insert(0, _backend_dir)

STATUS_LABEL = {"AC": "✅ 合っている", "WA": "❌ 違う", "RE": "💥 エラー", "TLE": "⏱  時間切れ"}
_COLUMN_MAX = 40


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def side_by_side(expected: str, actual: str) -> str:
    left, right = expected.rstrip("\n").split("\n"), actual.rstrip("\n").split("\n")
    width = min(_COLUMN_MAX, max([_width("期待する出力")] + [_width(line) for line in left]))
    rows = [f"    {_pad('期待する出力', width)} | 実際の出力", f"    {'-' * width}-+-{'-' * 12}"]
    for i in range(max(len(left), len(right))):
        a = left[i] if i < len(left) else ""
        b = right[i] if i < len(right) else ""
        mark = "  " if a.split() == b.split() else "≠ "
        rows.append(f"  {mark}{_pad(a, width)} | {b}")
    return "\n".join(rows)


def indent(text: str) -> str:
    body = text.rstrip("\n") or "（なし）"
    return "\n".join(f"    {line}" for line in body.split("\n"))


def load_fallback_samples(ref) -> list[dict] | None:
    """終了済みのコンテストのサンプル（保存済み → なければ問題ページ）。使えなければ理由を表示して None。

    data/editorials のサンプルは、終了済みのコンテストについてだけ保存される
    （解説ストアの作成と、終了後にだけ使える振り返り）ので、あればそのまま使う。
    """
    import httpx

    from app.services.contests import find_contest, finished_error
    from app.services.editorial_scraper import AtCoderClient, parse_samples, problem_dir

    saved = problem_dir(ref.task_id) / "samples.json"
    if saved.exists():
        samples = json.loads(saved.read_text(encoding="utf-8"))
        source = "保存済みのサンプル"
    else:
        try:
            error = finished_error(find_contest(ref.contest_id))
        except httpx.HTTPError as e:
            print(f"コンテストの終了時刻を確認できませんでした（{type(e).__name__}）。")
            return None
        if error:
            print("コンテスト中（または終了を確認できない）ため、問題ページは自動で取得しません。")
            return None
        client = AtCoderClient(interval=1.5)
        try:
            samples = parse_samples(client.get(f"{ref.url}?lang=ja"))
        finally:
            client.close()
        source = "問題ページのサンプル"
    print(f"（{ref.letter}.txt が空のため、{source}を使います）\n")
    return [{"index": i, **s} for i, s in enumerate(samples, 1)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("contest_id", nargs="?", help="コンテストID（例: abc477）")
    parser.add_argument("letter", nargs="?", help="問題の記号（例: c）")
    parser.add_argument("--file", help="c.py または c.txt のパス（VS Code のタスク用）")
    args = parser.parse_args()

    file_arg = Path(args.file).resolve() if args.file else None
    os.chdir(_backend_dir)  # backend/.env（SUBMISSIONS_DIR など）を読むため

    from app.services.tutor import run_samples
    from app.services.workspace import make_ref, parse_sample_file, ref_from_path, resolve_submissions_dir

    try:
        if file_arg:
            ref = ref_from_path(file_arg)
            folder = file_arg.parent
        elif args.contest_id and args.letter:
            ref = make_ref(args.contest_id, args.letter)
            folder = resolve_submissions_dir() / ref.contest_id
        else:
            parser.error("「abc477 c」のようにコンテストと問題を指定するか、--file を指定してください")
    except ValueError as e:
        print(f"エラー: {e}")
        return 2

    code_path, sample_path = folder / f"{ref.letter}.py", folder / f"{ref.letter}.txt"
    print(f"{ref.contest_id.upper()} {ref.letter.upper()}  {code_path}")
    if not code_path.exists():
        print(f"エラー: {code_path} がありません。python scripts/new_contest.py {ref.contest_id} で作れます")
        return 2

    cases = parse_sample_file(sample_path.read_text(encoding="utf-8")) if sample_path.exists() else []
    if not cases:
        cases = load_fallback_samples(ref)
        if not cases:
            print(f"{sample_path.name} に入力例を貼ってから試してください。")
            return 2

    check = run_samples(code_path.read_text(encoding="utf-8"), [{"input": c["input"], "output": c["output"]} for c in cases])
    ok = 0
    for case, result in zip(cases, check.cases):
        has_expected = bool(case["output"].strip())
        if result.status in ("RE", "TLE"):
            label = STATUS_LABEL[result.status]
        elif not has_expected:
            label = "▶ 実行しました（出力例なし）"
        else:
            label = STATUS_LABEL[result.status]
        print(f"[ケース {case['index']}] {label}")

        if result.status == "WA" and has_expected:
            print(side_by_side(case["output"], result.actual))
        elif result.status == "TLE":
            print("    2 秒以内に終わりませんでした")
        elif not has_expected:
            print("  実際の出力:")
            print(indent(result.actual))
        if result.status == "RE":
            print("  エラー:")
            # 実行は一時フォルダの main.py で行うので、表示上は自分のファイル名に戻す
            print(indent(re.sub(r'File "[^"]*main\.py"', f'File "{code_path.name}"', result.stderr)))
        ok += result.status == "AC" or (not has_expected and result.status not in ("RE", "TLE"))
        print()

    print(f"結果: {ok}/{len(cases)} ケース OK")
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
