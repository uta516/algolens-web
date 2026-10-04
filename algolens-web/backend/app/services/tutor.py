"""RAG 家庭教師: 提出コードから最小修正・ずれの解説・似た問題を返す（docs/rag-tutor-design.md）。

流れ（explain）:
  1. LLM 1 回目で最小修正コード・計算量・計算回数の目安・最大サイズの入力を作るコードを JSON で受け取る
  2. 修正コードを確かめ、だめなら 1 をやり直す（最大 2 回）
     - 計算回数の目安が多すぎれば実行せずにやり直す
     - 保存済みサンプルで実行する
     - 最大サイズの入力で実行し、制限時間内に終わるかを測る
  3. 差分の大きさで「書き方」「考え方」に分ける
  4. mistake_logs に保存し、同じミスの種類の過去回数を数える
  5. 公式解説ストアを 2 通りの文章で検索する（本問は除く）
  6. AC 済みなら「参考」、未 AC なら「次に解く問題」に分ける
  7. LLM 2 回目で解説を生成する（公式解説の本文は渡さない）

LLM・検索・AC 判定は引数で差し替えられるようにして、テストでは偽物を渡す。
"""

import difflib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Protocol, Sequence

from bs4 import BeautifulSoup
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.mistake_log import FIX_CONFIRMED, FIX_FAILED, MISTAKE_LEVELS, MISTAKE_TYPES, MistakeLog
from app.services.editorial_scraper import EDITORIALS_DIR, load_meta, problem_dir

SAMPLE_TIME_LIMIT_SEC = 2.0
DEFAULT_TIME_LIMIT_SEC = 2.0   # 問題ページから制限時間を読めなかったとき
MAX_RETRIES = 2              # 1 回目に加えてやり直す回数
OPS_LIMIT = 10**9            # 計算回数の目安がこれ（10^8 の 10 倍）を超えたら実行せずに作り直す
CPYTHON_TIME_FACTOR = 5      # PyPy がないとき、CPython では制限時間をこの倍率で緩める
GENERATOR_TIME_LIMIT_SEC = 10.0
MAX_INPUT_BYTES = 64 * 1024 * 1024
SUBMIT_VERDICTS = ("AC", "WA", "TLE", "RE")
SMALL_DIFF_MAX_LINES = 3     # 変更がこの行数以下なら「書き方」
SMALL_DIFF_MAX_RATIO = 0.2   # 変更が元コードのこの割合以下なら「書き方」
SIMILAR_K = 3
_STATEMENT_MAX_CHARS = 6000
_FLOAT_TOL = 1e-6


class TutorError(Exception):
    """LLM の出力が使えないなど、解説を作れなかったときの例外。"""


# ---------------------------------------------------------------------------
# 差分と分岐
# ---------------------------------------------------------------------------

def _normalize_lines(code: str) -> list[str]:
    code = code.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in code.split("\n")]
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def compute_diff(original: str, fixed: str) -> tuple[str, int, int]:
    """unified diff の文字列・変更行数・元コードの行数を返す。

    変更行数は「置き換えは行数の多い方、追加・削除はその行数」の合計。
    1 行だけ書き換えた場合は 1 行と数える。行末の空白と改行コードの違いは無視する。
    """
    a, b = _normalize_lines(original), _normalize_lines(fixed)
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "equal":
            changed += max(i2 - i1, j2 - j1)
    diff = "\n".join(
        difflib.unified_diff(a, b, fromfile="original", tofile="fixed", lineterm="")
    )
    return diff, changed, len(a)


def classify_level(changed_lines: int, total_lines: int, samples_passed: bool | None) -> str:
    """サンプルを通らなければ「考え方」。通った（または未確認）なら差分の大きさで判定する。"""
    if samples_passed is False:
        return "考え方"
    if changed_lines <= SMALL_DIFF_MAX_LINES:
        return "書き方"
    if total_lines > 0 and changed_lines / total_lines <= SMALL_DIFF_MAX_RATIO:
        return "書き方"
    return "考え方"


# ---------------------------------------------------------------------------
# サンプル実行
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CaseResult:
    index: int
    status: str  # AC / WA / TLE / RE
    input: str
    expected: str
    actual: str = ""
    stderr: str = ""


@dataclass(frozen=True)
class SampleCheck:
    passed: bool | None  # サンプルがなければ None
    cases: list[CaseResult] = field(default_factory=list)

    def first_failure(self) -> CaseResult | None:
        return next((c for c in self.cases if c.status != "AC"), None)


def _tokens_equal(expected: str, actual: str) -> bool:
    if expected == actual:
        return True
    try:
        e, a = float(expected), float(actual)
    except ValueError:
        return False
    if math.isnan(e) or math.isnan(a):
        return False
    return math.isclose(e, a, rel_tol=_FLOAT_TOL, abs_tol=_FLOAT_TOL)


def outputs_match(expected: str, actual: str) -> bool:
    """空白区切りのトークン単位で比較する。小数は 1e-6 までの誤差を許す。"""
    e, a = expected.split(), actual.split()
    return len(e) == len(a) and all(_tokens_equal(x, y) for x, y in zip(e, a))


def run_samples(
    code: str, samples: list[dict], time_limit: float = SAMPLE_TIME_LIMIT_SEC
) -> SampleCheck:
    """コードを別プロセスの Python で各サンプルに対して実行する。

    LLM が書いたコードを手元で動かすため、-I（環境変数・ユーザー site を無視）で起動し、
    作業ディレクトリは一時ディレクトリにする。
    """
    if not samples:
        return SampleCheck(passed=None)

    cases = []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "main.py"
        path.write_text(code, encoding="utf-8")
        for i, sample in enumerate(samples, 1):
            cases.append(_run_case(path, i, sample, time_limit, tmp))
    return SampleCheck(passed=all(c.status == "AC" for c in cases), cases=cases)


def _run_case(path: Path, index: int, sample: dict, time_limit: float, cwd: str) -> CaseResult:
    expected = sample["output"]
    base = dict(index=index, input=sample["input"], expected=expected)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-X", "utf8", str(path)],
            input=sample["input"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=time_limit,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired:
        return CaseResult(status="TLE", **base)
    if proc.returncode != 0:
        return CaseResult(status="RE", actual=proc.stdout, stderr=proc.stderr[-2000:], **base)
    status = "AC" if outputs_match(expected, proc.stdout) else "WA"
    return CaseResult(status=status, actual=proc.stdout, **base)


# ---------------------------------------------------------------------------
# 最大サイズの入力での実行
# ---------------------------------------------------------------------------

STRESS_OK = "ok"
STRESS_TLE = "TLE"
STRESS_SKIPPED = "skipped"


@dataclass(frozen=True)
class StressCheck:
    status: str          # STRESS_OK / STRESS_TLE / STRESS_SKIPPED
    interpreter: str     # "PyPy" / "CPython"
    time_limit: float    # 実際に使った制限時間（CPython なら緩めた値）
    seconds: float | None = None
    input_bytes: int = 0
    note: str = ""       # 飛ばした理由


def find_pypy() -> str | None:
    """PyPy の実行ファイル。環境変数 PYPY_PATH か PATH 上の pypy3 / pypy を探す。"""
    path = os.environ.get("PYPY_PATH")
    if path and Path(path).is_file():
        return path
    return shutil.which("pypy3") or shutil.which("pypy")


def stress_interpreter(problem_time_limit: float) -> tuple[list[str], str, float]:
    """(起動コマンド, 名前, 制限時間)。PyPy がなければ CPython で制限時間を緩める。"""
    pypy = find_pypy()
    if pypy:
        return [pypy, "-I"], "PyPy", problem_time_limit
    return [sys.executable, "-I", "-X", "utf8"], "CPython", problem_time_limit * CPYTHON_TIME_FACTOR


def run_stress(code: str, generator: str, problem_time_limit: float = DEFAULT_TIME_LIMIT_SEC) -> StressCheck:
    """generator で最大サイズの入力を作り、修正コードがその入力で制限時間内に終わるかを測る。

    generator が失敗したり出力が空・大きすぎる、または修正コードがエラーで止まった
    （入力が形式どおりでない可能性がある）場合は確認を飛ばして STRESS_SKIPPED を返す。
    """
    command, name, limit = stress_interpreter(problem_time_limit)

    def skipped(note: str, size: int = 0) -> StressCheck:
        return StressCheck(STRESS_SKIPPED, name, limit, input_bytes=size, note=note)

    if not generator.strip():
        return skipped("最大サイズの入力を作るコードがありませんでした")

    with tempfile.TemporaryDirectory() as tmp:
        gen_path, main_path, input_path = Path(tmp) / "gen.py", Path(tmp) / "main.py", Path(tmp) / "input.txt"
        gen_path.write_text(generator, encoding="utf-8")
        main_path.write_text(code, encoding="utf-8")

        # 出力はメモリに溜めずファイルに書く
        with open(input_path, "wb") as out:
            try:
                gen = subprocess.run(
                    [sys.executable, "-I", "-X", "utf8", str(gen_path)],
                    stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.PIPE,
                    timeout=GENERATOR_TIME_LIMIT_SEC, cwd=tmp,
                )
            except subprocess.TimeoutExpired:
                return skipped(f"入力を作るコードが {GENERATOR_TIME_LIMIT_SEC:g} 秒以内に終わりませんでした")
        size = input_path.stat().st_size
        if gen.returncode != 0:
            err = gen.stderr.decode("utf-8", "replace")[-300:]
            return skipped(f"入力を作るコードがエラーで止まりました: {err}", size)
        if size == 0:
            return skipped("入力を作るコードの出力が空でした")
        if size > MAX_INPUT_BYTES:
            return skipped(f"作った入力が大きすぎます（{size / 1024 / 1024:.0f} MB）", size)

        with open(input_path, "rb") as stdin:
            started = time.perf_counter()
            try:
                proc = subprocess.run(
                    [*command, str(main_path)],
                    stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    timeout=limit, cwd=tmp,
                )
            except subprocess.TimeoutExpired:
                return StressCheck(STRESS_TLE, name, limit, input_bytes=size)
            seconds = time.perf_counter() - started
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace")[-300:]
        return skipped(f"修正版がエラーで止まりました（作った入力が形式どおりでない可能性があります）: {err}", size)
    return StressCheck(STRESS_OK, name, limit, seconds=seconds, input_bytes=size)


# ---------------------------------------------------------------------------
# 保存済みの問題データ
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProblemData:
    problem_id: str
    contest_id: str
    title: str
    statement: str
    samples: list[dict]
    time_limit_sec: float = DEFAULT_TIME_LIMIT_SEC


def parse_time_limit(html: str) -> float:
    m = re.search(r"実行時間制限:\s*([\d.]+)\s*sec", html)
    return float(m.group(1)) if m else DEFAULT_TIME_LIMIT_SEC


def load_problem(problem_id: str, base_dir: Path = EDITORIALS_DIR) -> ProblemData | None:
    """data/editorials/{problem_id}/ から問題文（日本語）とサンプルを読む。未取得なら None。"""
    meta = load_meta(problem_id, base_dir)
    pdir = problem_dir(problem_id, base_dir)
    task_path = pdir / "task.html"
    if meta is None or not task_path.exists():
        return None

    html = task_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#task-statement span.lang-ja") or soup.select_one("#task-statement")
    statement = root.get_text("\n", strip=True) if root else ""

    samples_path = pdir / "samples.json"
    samples = json.loads(samples_path.read_text(encoding="utf-8")) if samples_path.exists() else []
    return ProblemData(
        problem_id=problem_id,
        contest_id=meta.get("contest_id", ""),
        title=meta.get("title", ""),
        statement=statement[:_STATEMENT_MAX_CHARS],
        samples=samples,
        time_limit_sec=parse_time_limit(html),
    )


# ---------------------------------------------------------------------------
# 記録帳
# ---------------------------------------------------------------------------

def save_mistake_log(db: Session, **fields) -> MistakeLog:
    if fields.get("mistake_type") not in MISTAKE_TYPES:
        raise ValueError(f"mistake_type が選択肢にありません: {fields.get('mistake_type')}")
    if fields.get("mistake_level") not in MISTAKE_LEVELS:
        raise ValueError(f"mistake_level が選択肢にありません: {fields.get('mistake_level')}")
    log = MistakeLog(**fields)
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def count_past_same_type(db: Session, mistake_type: str, exclude_id: int | None = None) -> int:
    """同じ mistake_type の記録の件数。exclude_id を渡すとその記録（今回の分）を除く。

    「修正失敗」の記録は、ミスの見立て自体が外れていた可能性があるため数えない。
    """
    stmt = select(func.count(MistakeLog.id)).where(
        MistakeLog.mistake_type == mistake_type,
        or_(MistakeLog.fix_status.is_(None), MistakeLog.fix_status != FIX_FAILED),
    )
    if exclude_id is not None:
        stmt = stmt.where(MistakeLog.id != exclude_id)
    return db.scalar(stmt) or 0


# ---------------------------------------------------------------------------
# LLM プロンプト
# ---------------------------------------------------------------------------

FIRST_PASS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "fixed_code": {"type": "STRING"},
        "gap_summary": {"type": "STRING"},
        "mistake_type": {"type": "STRING", "enum": list(MISTAKE_TYPES)},
        "lesson": {"type": "STRING"},
        "correct_idea": {"type": "STRING"},
        "complexity": {"type": "STRING"},
        "estimated_ops": {"type": "NUMBER"},
        "max_input_generator": {"type": "STRING"},
    },
    "required": [
        "fixed_code", "gap_summary", "mistake_type", "lesson", "correct_idea",
        "complexity", "estimated_ops", "max_input_generator",
    ],
}

EXPLANATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"explanation": {"type": "STRING"}},
    "required": ["explanation"],
}


def number_lines(code: str) -> str:
    """プロンプト用に "  3| print(x)" の形で行番号を付ける。"""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}}| {line}" for i, line in enumerate(lines, 1))


# Gemini には学習者本人の言葉で頼み、文章中で学習者を「あなた」と呼ばせる
ADDRESS_RULE = "文章では私のことを「あなた」と呼んでください（「生徒」「生徒さん」とは書かない）。"


def build_first_prompt(
    problem: ProblemData, code: str, verdict: str, feedback: str = "", previous_failure: str = ""
) -> str:
    """previous_failure: 前回の修正版を提出して通らなかったときの内容（やり直しのたびに渡す）。"""
    previous = f"\n## 前回の修正版を提出した結果\n{previous_failure}\n" if previous_failure else ""
    retry = f"\n## 前回の修正案の問題点\n{feedback}\nこれを踏まえて修正し直してください。\n" if feedback else ""
    return f"""AtCoder の家庭教師として答えてください。私の Python 提出コードが {verdict} になりました。
私のコードを最小限だけ直して AC させてください。
{ADDRESS_RULE}

## 守ること（最重要）
- 元のコードの構造・変数名・書き方をできるだけ残し、バグの原因の行だけを直す
- 全体の書き直しは禁止。関数の分割・変数名の変更・処理の追加による整理もしない
- 直す行が少ないほど良い修正とみなす
- ただし、制約の上限の入力でも制限時間（{problem.time_limit_sec:g} 秒）に間に合う計算量にする。
  元のやり方では間に合わない場合だけ、間に合うのに必要な分を書き換えてよい

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 私のコード（判定: {verdict}。各行の先頭は行番号）
```
{number_lines(code)}
```
{previous}{retry}
## 出力（JSON）
- fixed_code: 修正後の Python コード全体（行番号とコードブロック記号は付けない）
- gap_summary: 私の考えと正解のずれを一文で（直した行番号を含める）
- mistake_type: 次から 1 つ: {", ".join(MISTAKE_TYPES)}
- lesson: 次に同じミスをしないための教訓を一文で
- correct_idea: この問題を解く正しい考え方を一文で（使う手法名があれば手法名を含める）
- complexity: fixed_code の時間計算量（例: "O(N log N)"）
- estimated_ops: 制約の上限での fixed_code の計算回数の目安（数値。例: N=2×10^5 で O(N log N) なら 3600000）
- max_input_generator: 制約の上限に近い入力を 1 つ作って標準出力に書く Python コード
  - 入力形式と制約を必ず守る（上限ちょうどの大きさにする）
  - fixed_code が最も遅くなる形の入力にする
  - 乱数を使うなら random.seed(0) で固定する。標準入力は読まない。コードブロック記号は付けない
"""


def build_explanation_prompt(
    problem: ProblemData,
    code: str,
    fixed_code: str,
    diff: str,
    gap_summary: str,
    correct_idea: str,
    mistake_type: str,
    past_count: int,
    similar: Sequence["SimilarProblem"],
    complexity: str = "",
) -> str:
    similar_lines = "\n".join(f"- {p.problem_id}: {p.title}" for p in similar) or "- なし"
    return f"""AtCoder の家庭教師として、私の提出コードについて最終的な解説を書いてください。
{ADDRESS_RULE}

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 私のコード
```python
{code}
```

## 最小修正したコード
```python
{fixed_code}
```

## 差分
```diff
{diff}
```

## 分析済みの内容
- ずれ: {gap_summary}
- 正しい考え方: {correct_idea}
- 修正版の計算量: {complexity or "不明"}
- ミスの種類: {mistake_type}（この種類のミスは過去に {past_count} 回）

## 似た問題（問題IDとタイトルのみ）
{similar_lines}

## 出力（JSON）
- explanation: Markdown の解説。次の順で簡潔に。
  1. どこがずれていたか（差分の行を指して）
  2. 正しい考え方
  3. 同じミスを繰り返さないためのチェックポイント（過去の回数に触れる）
  4. 似た問題で何を確かめるとよいか（問題IDを挙げる。中身は推測で書かない）
"""


def _strip_code_fence(code: str) -> str:
    m = re.match(r"^\s*```[a-zA-Z0-9]*\n(.*?)\n?```\s*$", code, re.DOTALL)
    return m.group(1) if m else code


def _failure_feedback(check: SampleCheck) -> str:
    fail = check.first_failure()
    if fail is None:
        return ""
    msg = f"サンプル {fail.index} が {fail.status} でした。\n入力:\n{fail.input}\n期待する出力:\n{fail.expected}\n"
    if fail.status == "WA":
        msg += f"実際の出力:\n{fail.actual}\n"
    if fail.status == "RE":
        msg += f"エラー:\n{fail.stderr[-800:]}\n"
    if fail.status == "TLE":
        msg += f"{SAMPLE_TIME_LIMIT_SEC:g} 秒以内に終わりませんでした。\n"
    return msg


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

# (prompt, response_schema) -> 解析済み JSON
Generate = Callable[[str, dict], dict]


class Searcher(Protocol):
    def search(self, text: str, k: int, exclude_problem_ids: Sequence[str]) -> list: ...


@dataclass(frozen=True)
class SimilarProblem:
    problem_id: str
    title: str
    contest_id: str
    difficulty: float | None
    reasons: list[str]  # "解き方が同じ" / "落とし穴が同じ"
    url: str


@dataclass(frozen=True)
class FirstPass:
    fixed_code: str
    gap_summary: str
    mistake_type: str
    lesson: str
    correct_idea: str
    complexity: str
    estimated_ops: float | None   # LLM が数値を返さなければ None
    generator: str
    check: SampleCheck
    stress: StressCheck | None    # 実行しなかった（目安が多すぎる・サンプル不通過）なら None
    attempts: int
    ops_too_large: bool = False

    @property
    def accepted(self) -> bool:
        """作り直しが要らない状態か（サンプルが通り、目安も最大サイズの入力も問題ない）。"""
        return (
            not self.ops_too_large
            and self.check.passed is not False
            and (self.stress is None or self.stress.status != STRESS_TLE)
        )


@dataclass(frozen=True)
class TutorResult:
    log: MistakeLog
    total_lines: int
    sample_cases: list[CaseResult]
    attempts: int
    past_same_type_count: int
    reference: list[SimilarProblem]
    next_problems: list[SimilarProblem]
    explanation: str
    warnings: list[str]
    complexity: str = ""
    estimated_ops: float | None = None
    stress: StressCheck | None = None


def _parse_ops(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    if isinstance(value, str):
        try:
            return _parse_ops(float(value.replace(",", "").strip()))
        except ValueError:
            return None
    return None


def _parse_first_pass(data: dict) -> dict | None:
    """必須の項目が揃っていなければ None。計算量・目安・generator は欠けていても続ける（確認を飛ばす）。"""
    keys = ("fixed_code", "gap_summary", "mistake_type", "lesson", "correct_idea")
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in keys):
        return None
    if data["mistake_type"] not in MISTAKE_TYPES:
        return None
    complexity = data.get("complexity")
    generator = data.get("max_input_generator")
    return {k: data[k].strip() for k in keys} | {
        "fixed_code": _strip_code_fence(data["fixed_code"]),
        "complexity": complexity.strip() if isinstance(complexity, str) else "",
        "estimated_ops": _parse_ops(data.get("estimated_ops")),
        "generator": _strip_code_fence(generator) if isinstance(generator, str) else "",
    }


TOO_LARGE_FEEDBACK = "変更が大きすぎる。元のコードを活かして必要な行だけ直して。"
STRESS_TLE_FEEDBACK = "最大サイズの入力で時間切れ。計算量を改善して。"


def _ops_feedback(ops: float, complexity: str) -> str:
    return (
        f"計算量 {complexity or '（不明）'} で、制約の上限での計算回数の目安が {ops:.1e} 回です。"
        "10^8 を大きく超えていて間に合いません。計算量を改善して。"
    )


def _changed_lines(code: str, fixed_code: str) -> int:
    return compute_diff(code, fixed_code)[1]


def _is_small_fix(code: str, fixed_code: str) -> bool:
    _, changed, total = compute_diff(code, fixed_code)
    return classify_level(changed, total, samples_passed=True) == "書き方"


Runner = Callable[[str, list[dict]], SampleCheck]
# (修正コード, generator, 問題の制限時間) -> StressCheck
StressRunner = Callable[[str, str, float], StressCheck]


def _verify(
    parsed: dict, problem: ProblemData, attempts: int, runner: Runner, stress_runner: StressRunner
) -> tuple[FirstPass, str]:
    """修正案を確かめて (結果, 作り直しの依頼文) を返す。依頼文が空なら作り直し不要。

    計算回数の目安 → サンプル → 最大サイズの入力 の順に確かめ、だめな時点で止める。
    """
    ops = parsed["estimated_ops"]
    if ops is not None and ops > OPS_LIMIT:
        # 実行はしない。サンプル結果は、上限までやり直してもだめだったときに表示用に取る
        fp = FirstPass(**parsed, check=SampleCheck(passed=None), stress=None, attempts=attempts, ops_too_large=True)
        return fp, _ops_feedback(ops, parsed["complexity"])
    check = runner(parsed["fixed_code"], problem.samples)
    if check.passed is False:
        return FirstPass(**parsed, check=check, stress=None, attempts=attempts), _failure_feedback(check)
    stress = stress_runner(parsed["fixed_code"], parsed["generator"], problem.time_limit_sec)
    fp = FirstPass(**parsed, check=check, stress=stress, attempts=attempts)
    return fp, (STRESS_TLE_FEEDBACK if stress.status == STRESS_TLE else "")


def generate_fix(
    generate: Generate,
    problem: ProblemData,
    code: str,
    verdict: str,
    runner: Runner = run_samples,
    stress_runner: StressRunner = run_stress,
    previous_failure: str = "",
) -> FirstPass:
    """LLM 1 回目 + 確認（計算回数の目安・サンプル・最大サイズの入力）。

    - どれかでだめなら、その内容を伝えて最大 MAX_RETRIES 回やり直し、最後の案を返す
    - 確認を通ったが差分が「書き方」の基準を超えたら、1 回だけ小さく直すよう頼み直す。
      やり直した案が確認を通り、サンプルも通り、かつ変更が小さくなった場合だけ差し替える
    """
    def ask(feedback: str) -> dict | None:
        prompt = build_first_prompt(problem, code, verdict, feedback, previous_failure)
        return _parse_first_pass(generate(prompt, FIRST_PASS_SCHEMA))

    feedback = ""
    last: FirstPass | None = None
    attempts = 0
    for _ in range(MAX_RETRIES + 1):
        attempts += 1
        parsed = ask(feedback)
        if parsed is None:
            feedback = "出力の JSON に必要な項目が欠けているか、mistake_type が選択肢にありませんでした。"
            continue
        last, feedback = _verify(parsed, problem, attempts, runner, stress_runner)
        if not feedback:
            break
    if last is None:
        raise TutorError("LLM から有効な修正案を得られませんでした")
    if last.ops_too_large:
        # 上限までやり直しても目安が多すぎた。サンプルの結果だけは表示できるよう取っておく
        last = replace(last, check=runner(last.fixed_code, problem.samples))
    if not last.accepted or last.check.passed is not True or _is_small_fix(code, last.fixed_code):
        return replace(last, attempts=attempts)

    attempts += 1
    parsed = ask(TOO_LARGE_FEEDBACK)
    if parsed is None:
        return replace(last, attempts=attempts)
    retried, feedback = _verify(parsed, problem, attempts, runner, stress_runner)
    if (
        not feedback
        and retried.check.passed is True
        and _changed_lines(code, retried.fixed_code) < _changed_lines(code, last.fixed_code)
    ):
        return retried
    return replace(last, attempts=attempts)


def _verification_warnings(fix: FirstPass) -> list[str]:
    warnings = []
    if fix.check.passed is None:
        warnings.append("保存済みのサンプルがないため、修正コードのサンプルでの確認を飛ばしました")
    elif fix.check.passed is False:
        warnings.append(f"{fix.attempts} 回試しましたが、修正コードはサンプルを通りませんでした")
    if fix.estimated_ops is None:
        warnings.append("計算回数の目安を得られなかったため、目安での確認を飛ばしました")
    elif fix.ops_too_large:
        warnings.append(
            f"{fix.attempts} 回試しましたが、計算回数の目安が {fix.estimated_ops:.1e} 回で "
            "10^8 を大きく超えたままです（最大サイズの入力での実行はしていません）"
        )
    stress = fix.stress
    if stress is not None and stress.status == STRESS_SKIPPED:
        warnings.append(f"最大サイズの入力での確認を飛ばしました: {stress.note}")
    elif stress is not None and stress.status == STRESS_TLE:
        warnings.append(
            f"{fix.attempts} 回試しましたが、修正版は最大サイズの入力で {stress.time_limit:g} 秒以内に"
            f"終わりませんでした（{stress.interpreter}）"
        )
    return warnings


def find_similar(
    searcher: Searcher | None,
    problem_id: str,
    body_text: str,
    correct_idea: str,
    warnings: list[str],
) -> list[SimilarProblem]:
    """検索1（本問の解説本文）と検索2（正しい考え方）の結果を、重複をまとめて返す。"""
    if searcher is None:
        warnings.append("公式解説ストアが使えないため、似た問題の検索を飛ばしました")
        return []
    queries = []
    if body_text:
        queries.append(("解き方が同じ", body_text))
    else:
        warnings.append(f"{problem_id} の公式解説が公開されていないため、検索1（同じ解き方）を飛ばしました")
    queries.append(("落とし穴が同じ", correct_idea))

    found: dict[str, SimilarProblem] = {}
    for reason, query in queries:
        for r in searcher.search(query, k=SIMILAR_K, exclude_problem_ids=[problem_id]):
            meta = r.metadata
            pid = meta["problem_id"]
            if pid in found:
                found[pid].reasons.append(reason)
                continue
            contest_id = meta.get("contest_id", "")
            found[pid] = SimilarProblem(
                problem_id=pid,
                title=meta.get("title", ""),
                contest_id=contest_id,
                difficulty=meta.get("difficulty"),
                reasons=[reason],
                url=f"https://atcoder.jp/contests/{contest_id}/tasks/{pid}",
            )
    return list(found.values())


def solved_problem_ids(db: Session, username: str | None = None) -> set[str]:
    """DB の提出データで AC 済みの問題 ID（解説ストアと同じ "abc300_c" 形式）。

    DB の atcoder_problem_id は "{contest_id}_{problem_id}" なので先頭の contest_id を外す。
    """
    from app.models.problem import Problem
    from app.models.submission import Submission
    from app.models.user import User

    stmt = (
        select(Problem.atcoder_problem_id, Problem.contest_id)
        .join(Submission, Submission.problem_id == Problem.id)
        .where(Submission.status == "AC")
    )
    if username:
        stmt = stmt.join(User, User.id == Submission.user_id).where(User.atcoder_username == username)
    solved = set()
    for aid, contest_id in db.execute(stmt).all():
        prefix = f"{contest_id}_"
        solved.add(aid[len(prefix):] if aid.startswith(prefix) else aid)
    return solved


def split_by_solved(
    db: Session, similar: list[SimilarProblem], username: str | None
) -> tuple[list[SimilarProblem], list[SimilarProblem]]:
    """似た問題を (AC 済み = 参考, 未 AC = 次に解く問題) に分ける。"""
    solved = solved_problem_ids(db, username)
    return (
        [p for p in similar if p.problem_id in solved],
        [p for p in similar if p.problem_id not in solved],
    )


def explain(
    db: Session,
    generate: Generate,
    searcher: Searcher | None,
    problem: ProblemData,
    code: str,
    verdict: str,
    body_text: str,
    username: str | None = None,
    runner: Runner = run_samples,
    generate_first: Generate | None = None,
    stress_runner: StressRunner = run_stress,
    retry_of: MistakeLog | None = None,
) -> TutorResult:
    """generate_first を渡すと、LLM 1 回目（修正案）だけそちらを使う。

    retry_of を渡すと、その記録の修正版を提出して通らなかったものとして作り直す。
    """
    warnings: list[str] = []
    previous_failure = ""
    if retry_of is not None:
        previous_failure = resubmit_feedback(retry_of)
        warnings.append(f"前回の修正版は提出して {retry_of.submitted_verdict} だったため、作り直した修正版です")

    # ① ② 修正案と確認（計算回数の目安・サンプル・最大サイズの入力）
    fix = generate_fix(
        generate_first or generate, problem, code, verdict, runner, stress_runner, previous_failure
    )
    warnings.extend(_verification_warnings(fix))

    # ③ 差分と分岐
    diff, changed, total = compute_diff(code, fix.fixed_code)
    level = classify_level(changed, total, fix.check.passed)

    # ④ 同じミスの過去回数（記録の保存は最後に行う）
    past = count_past_same_type(db, fix.mistake_type)

    # ⑤ ⑥ 似た問題を検索して AC 済み / 未 AC に分ける
    similar = find_similar(searcher, problem.problem_id, body_text, fix.correct_idea, warnings)
    reference, next_problems = split_by_solved(db, similar, username)

    # ⑦ 最終解説（公式解説の本文は渡さない）
    prompt = build_explanation_prompt(
        problem, code, fix.fixed_code, diff, fix.gap_summary, fix.correct_idea,
        fix.mistake_type, past, similar, fix.complexity,
    )
    explanation = generate(prompt, EXPLANATION_SCHEMA).get("explanation", "")
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = ""
        warnings.append("解説の生成に失敗しました（LLM の出力が空でした）")

    # ④ 記録帳: 途中で LLM が失敗したときに記録だけ残らないよう、すべて揃ってから保存する
    log = save_mistake_log(
        db,
        problem_id=problem.problem_id,
        original_code=code,
        fixed_code=fix.fixed_code,
        diff=diff,
        verdict=verdict,
        diff_lines=changed,
        mistake_level=level,
        mistake_type=fix.mistake_type,
        samples_passed=fix.check.passed,
        gap_summary=fix.gap_summary,
        correct_idea=fix.correct_idea,
        lesson=fix.lesson,
        retry_of_id=retry_of.id if retry_of is not None else None,
    )

    return TutorResult(
        log=log,
        total_lines=total,
        sample_cases=fix.check.cases,
        attempts=fix.attempts,
        past_same_type_count=past,
        reference=reference,
        next_problems=next_problems,
        explanation=explanation,
        warnings=warnings,
        complexity=fix.complexity,
        estimated_ops=fix.estimated_ops,
        stress=fix.stress,
    )


# ---------------------------------------------------------------------------
# 修正版を提出した結果
# ---------------------------------------------------------------------------

_RESUBMIT_HINTS = {
    "WA": "見落としている場合（境界・同じ値・最小や最大の入力など）がないか考え直して。",
    "TLE": "制約の上限の入力で時間切れになっている。計算量を改善して。",
    "RE": "インデックスの範囲・再帰の深さ・メモリの使い方を確認して。",
}


def resubmit_feedback(log: MistakeLog) -> str:
    """修正版を提出して通らなかったことを、LLM 1 回目に伝える文。"""
    return (
        f"前回の修正版を AtCoder に提出したところ {log.submitted_verdict} でした"
        f"（手元のサンプルは通っていました）。{_RESUBMIT_HINTS.get(log.submitted_verdict, '')}\n"
        f"前回の修正版:\n```\n{log.fixed_code}\n```"
    )


def has_retry(db: Session, log: MistakeLog) -> bool:
    return db.scalar(select(func.count(MistakeLog.id)).where(MistakeLog.retry_of_id == log.id)) > 0


def record_submit_result(db: Session, log: MistakeLog, submitted: str) -> MistakeLog:
    """修正版を提出した結果を記録する。AC なら「確認済み」、それ以外は「修正失敗」。

    「修正失敗」の記録は同じミスの回数の集計から外れる。
    結果は 1 回だけ記録できる（作り直しが失敗したときだけ、同じ結果でもう一度やり直せる）。
    """
    if submitted not in SUBMIT_VERDICTS:
        raise ValueError(f"提出結果が選択肢にありません: {submitted}")
    if log.fix_status == FIX_CONFIRMED:
        raise TutorError("この修正版は提出で AC を確認済みです")
    if log.fix_status == FIX_FAILED:
        if has_retry(db, log):
            raise TutorError("この修正版の提出結果は記録済みで、作り直しも済んでいます")
        if submitted != log.submitted_verdict:
            raise TutorError(f"この修正版の提出結果は {log.submitted_verdict} で記録済みです")
        return log
    log.fix_status = FIX_CONFIRMED if submitted == "AC" else FIX_FAILED
    log.submitted_verdict = submitted
    db.commit()
    db.refresh(log)
    return log
