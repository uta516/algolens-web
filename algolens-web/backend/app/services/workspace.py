"""コンテスト用の作業フォルダ（submissions/<contest_id>/<記号>.py / .txt）の扱い。

  submissions/abc477/c.py   自分の解答（VS Code で書く）
  submissions/abc477/c.txt  入力例・出力例を自分で貼るファイル（=== 入力1 === などの見出しで区切る）

問題文はファイルに入れない。c.txt に貼るサンプルも問題の一部なので、git には入れない（.gitignore）。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

ATCODER_BASE = "https://atcoder.jp"
DEFAULT_UPTO = "d"
SAMPLE_PAIRS = 3
# AtCoder/submissions/（app/core/config.py から 4 つ上が AtCoder/）
_DEFAULT_SUBMISSIONS_DIR = Path(__file__).resolve().parents[4] / "submissions"

_CONTEST_ID = re.compile(r"^[a-z]+[0-9]+$")
_LETTER = re.compile(r"^[a-z]$")
_HEADER = re.compile(r"^===\s*(入力|出力)\s*(\d+)\s*===\s*$")


def resolve_submissions_dir() -> Path:
    """SUBMISSIONS_DIR（未設定なら AtCorder/submissions/）。"""
    value = settings.submissions_dir.strip()
    return Path(value).expanduser() if value else _DEFAULT_SUBMISSIONS_DIR


# ---------------------------------------------------------------------------
# コンテスト・問題の記号・問題ID の対応
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProblemRef:
    contest_id: str  # "abc477"
    letter: str      # "c"
    task_id: str     # "abc477_c"（古い ABC は "abc001_3"）

    @property
    def url(self) -> str:
        return f"{ATCODER_BASE}/contests/{self.contest_id}/tasks/{self.task_id}"


def task_id_for(contest_id: str, letter: str) -> str:
    """コンテストと問題の記号から AtCoder の問題IDを作る。

    ABC001〜ABC019 と ARC001〜ARC034 は問題IDの末尾が数字（abc001_3 = C 問題）。
    """
    contest_id, letter = contest_id.lower(), letter.lower()
    m = re.match(r"^(abc|arc)(\d+)$", contest_id)
    if m and int(m.group(2)) <= {"abc": 19, "arc": 34}[m.group(1)]:
        return f"{contest_id}_{ord(letter) - ord('a') + 1}"
    return f"{contest_id}_{letter}"


def make_ref(contest_id: str, letter: str) -> ProblemRef:
    contest_id, letter = contest_id.lower(), letter.lower()
    if not _CONTEST_ID.match(contest_id):
        raise ValueError(f"コンテストIDの形が正しくありません: {contest_id}（例: abc477）")
    if not _LETTER.match(letter):
        raise ValueError(f"問題の記号は英字 1 文字で指定してください: {letter}（例: c）")
    return ProblemRef(contest_id, letter, task_id_for(contest_id, letter))


def ref_from_path(path: Path) -> ProblemRef:
    """…/<contest_id>/<記号>.py または .txt のパスから問題を読み取る。"""
    path = Path(path)
    if path.suffix.lower() not in (".py", ".txt"):
        raise ValueError(f"{path.name} は問題のファイルではありません（c.py か c.txt を開いてください）")
    return make_ref(path.parent.name, path.stem)


def problem_letters(upto: str = DEFAULT_UPTO) -> list[str]:
    upto = upto.lower()
    if not _LETTER.match(upto):
        raise ValueError(f"--upto は英字 1 文字で指定してください: {upto}")
    return [chr(c) for c in range(ord("a"), ord(upto) + 1)]


# ---------------------------------------------------------------------------
# ファイルの作成（new_contest.py）
# ---------------------------------------------------------------------------

def code_template(ref: ProblemRef) -> str:
    return f"""# {ref.contest_id.upper()} {ref.letter.upper()}
# {ref.url}
#
# よく使う入力の書き方:
#   N = int(input())
#   N, M = map(int, input().split())
#   A = list(map(int, input().split()))
#   S = input()
#   grid = [input() for _ in range(H)]
#   edges = [tuple(map(int, input().split())) for _ in range(M)]
#   import sys; input = sys.stdin.readline  # 入力が多いとき（文字列は末尾の改行に注意）

"""


def sample_template(pairs: int = SAMPLE_PAIRS) -> str:
    blocks = []
    for i in range(1, pairs + 1):
        blocks += [f"=== 入力{i} ===", "", f"=== 出力{i} ===", ""]
    return "\n".join(blocks) + "\n"


def create_contest_files(base_dir: Path, contest_id: str, upto: str = DEFAULT_UPTO) -> list[tuple[Path, bool]]:
    """base_dir/<contest_id>/ に問題ごとの .py と .txt を作る。

    すでにあるファイルは上書きしない。(パス, 新しく作ったか) の一覧を返す。
    """
    letters = problem_letters(upto)
    refs = [make_ref(contest_id, letter) for letter in letters]
    folder = Path(base_dir) / refs[0].contest_id
    folder.mkdir(parents=True, exist_ok=True)

    results = []
    for ref in refs:
        for path, content in (
            (folder / f"{ref.letter}.py", code_template(ref)),
            (folder / f"{ref.letter}.txt", sample_template()),
        ):
            if path.exists():
                results.append((path, False))
                continue
            path.write_text(content, encoding="utf-8", newline="\n")
            results.append((path, True))
    return results


# ---------------------------------------------------------------------------
# c.txt の読み取り（test.py）
# ---------------------------------------------------------------------------

def _normalize(text: str) -> str:
    """前後の空行を除き、末尾に改行を 1 つ付ける（空なら空文字）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"{text}\n" if text.strip() else ""


def parse_sample_file(text: str) -> list[dict]:
    """=== 入力N === / === 出力N === の見出しで入力と出力を組にする。

    入力も出力も空の組は飛ばす。出力だけ空の組は残す（実際の出力だけ表示する）。
    見出しより前の文字は無視する。番号順に並べて返す: [{"index", "input", "output"}, ...]
    """
    sections: dict[tuple[str, int], list[str]] = {}
    current: tuple[str, int] | None = None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _HEADER.match(line.strip())
        if m:
            current = (m.group(1), int(m.group(2)))
            sections.setdefault(current, [])
        elif current is not None:
            sections[current].append(line)

    numbers = sorted({n for _, n in sections})
    pairs = []
    for n in numbers:
        inp = _normalize("\n".join(sections.get(("入力", n), [])))
        out = _normalize("\n".join(sections.get(("出力", n), [])))
        if not inp and not out:
            continue
        pairs.append({"index": n, "input": inp, "output": out})
    return pairs


# ---------------------------------------------------------------------------
# 振り返りでのファイルの見つけ方
# ---------------------------------------------------------------------------

CODE_EXTENSIONS = (".py", ".txt")


def has_code(text: str) -> bool:
    """空行とコメント以外の行があるか（new_contest.py で作ったままの .py は False）。"""
    return any(line.strip() and not line.strip().startswith("#") for line in text.splitlines())


def find_local_code(
    base_dir: Path | None,
    contest_id: str,
    problem_index: str,
    problem_id: str,
) -> str | None:
    """手元のフォルダから提出コードを探して返す（なければ None）。

    1. base_dir/<contest_id>/<記号>.py（new_contest.py の形。古い ABC でも記号で対応する）
    2. ファイル名に問題IDを含むファイル（例: abc476_d.py / abc476_d_wa.py。サブフォルダも探し、
       複数あれば更新日時が最も新しいもの）

    中身がコメントだけのファイル（作ったまま書いていない）は、ないものとして扱う。
    """
    if base_dir is None or not Path(base_dir).is_dir():
        return None
    base_dir = Path(base_dir)

    contest_file = base_dir / contest_id.lower() / f"{problem_index.lower()}.py"
    if contest_file.is_file():
        text = contest_file.read_text(encoding="utf-8", errors="replace")
        if has_code(text):
            return text

    pattern = re.compile(rf"(?<![a-z0-9]){re.escape(problem_id.lower())}(?![a-z0-9])")
    candidates = [
        path for path in base_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in CODE_EXTENSIONS and pattern.search(path.stem.lower())
    ]
    for path in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        text = path.read_text(encoding="utf-8", errors="replace")
        if has_code(text):
            return text
    return None
