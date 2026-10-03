"""RAG 家庭教師: 提出コードから最小修正・ずれの解説・似た問題を返す（docs/rag-tutor-design.md）。

流れ（explain）:
  1. LLM 1 回目で最小修正コードなどを JSON で受け取る
  2. 修正コードを保存済みサンプルで実行し、通らなければ 1 をやり直す（最大 2 回）
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
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol, Sequence

from bs4 import BeautifulSoup
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.mistake_log import MISTAKE_LEVELS, MISTAKE_TYPES, MistakeLog
from app.services.editorial_scraper import EDITORIALS_DIR, load_meta, problem_dir

SAMPLE_TIME_LIMIT_SEC = 2.0
MAX_RETRIES = 2              # 1 回目に加えてやり直す回数
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
# 保存済みの問題データ
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProblemData:
    problem_id: str
    contest_id: str
    title: str
    statement: str
    samples: list[dict]


def load_problem(problem_id: str, base_dir: Path = EDITORIALS_DIR) -> ProblemData | None:
    """data/editorials/{problem_id}/ から問題文（日本語）とサンプルを読む。未取得なら None。"""
    meta = load_meta(problem_id, base_dir)
    pdir = problem_dir(problem_id, base_dir)
    task_path = pdir / "task.html"
    if meta is None or not task_path.exists():
        return None

    soup = BeautifulSoup(task_path.read_text(encoding="utf-8"), "html.parser")
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


def count_past_same_type(db: Session, mistake_type: str, exclude_id: int) -> int:
    """同じ mistake_type の記録のうち、今回の記録を除いた件数。"""
    stmt = select(func.count(MistakeLog.id)).where(
        MistakeLog.mistake_type == mistake_type, MistakeLog.id != exclude_id
    )
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
    },
    "required": ["fixed_code", "gap_summary", "mistake_type", "lesson", "correct_idea"],
}

EXPLANATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"explanation": {"type": "STRING"}},
    "required": ["explanation"],
}


def build_first_prompt(problem: ProblemData, code: str, verdict: str, feedback: str = "") -> str:
    retry = f"\n## 前回の修正案の問題点\n{feedback}\nこれを踏まえて修正し直してください。\n" if feedback else ""
    return f"""あなたは AtCoder の家庭教師です。生徒の Python 提出コードが {verdict} になりました。
生徒のコードをできるだけ残したまま、AC するための最小限の修正を行ってください。
全面的な書き直しは、元の方針では AC できない場合に限ります。

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 生徒のコード（判定: {verdict}）
```python
{code}
```
{retry}
## 出力（JSON）
- fixed_code: 修正後の Python コード全体（標準入力から読み、標準出力に書く。コードブロック記号は付けない）
- gap_summary: 生徒の考えと正解のずれを一文で
- mistake_type: 次から 1 つ: {", ".join(MISTAKE_TYPES)}
- lesson: 次に同じミスをしないための教訓を一文で
- correct_idea: この問題を解く正しい考え方を一文で（使う手法名があれば手法名を含める）
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
) -> str:
    similar_lines = "\n".join(f"- {p.problem_id}: {p.title}" for p in similar) or "- なし"
    return f"""あなたは AtCoder の家庭教師です。生徒の提出コードについて、最終的な解説を書いてください。

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 生徒のコード
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
    check: SampleCheck
    attempts: int


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


def _parse_first_pass(data: dict) -> dict | None:
    keys = ("fixed_code", "gap_summary", "mistake_type", "lesson", "correct_idea")
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in keys):
        return None
    if data["mistake_type"] not in MISTAKE_TYPES:
        return None
    return {k: data[k].strip() for k in keys} | {"fixed_code": _strip_code_fence(data["fixed_code"])}


def generate_fix(
    generate: Generate,
    problem: ProblemData,
    code: str,
    verdict: str,
    runner: Callable[[str, list[dict]], SampleCheck] = run_samples,
) -> FirstPass:
    """LLM 1 回目 + サンプル確認。通らなければ最大 MAX_RETRIES 回やり直し、最後の案を返す。"""
    feedback = ""
    last: FirstPass | None = None
    for attempt in range(1, MAX_RETRIES + 2):
        parsed = _parse_first_pass(generate(build_first_prompt(problem, code, verdict, feedback), FIRST_PASS_SCHEMA))
        if parsed is None:
            feedback = "出力の JSON に必要な項目が欠けているか、mistake_type が選択肢にありませんでした。"
            continue
        check = runner(parsed["fixed_code"], problem.samples)
        last = FirstPass(**parsed, check=check, attempts=attempt)
        if check.passed is not False:
            return last
        feedback = _failure_feedback(check)
    if last is None:
        raise TutorError("LLM から有効な修正案を得られませんでした")
    return last


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
        warnings.append(f"{problem_id} の公式解説本文がないため、検索1を飛ばしました")
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


def explain(
    db: Session,
    generate: Generate,
    searcher: Searcher | None,
    problem: ProblemData,
    code: str,
    verdict: str,
    body_text: str,
    username: str | None = None,
    runner: Callable[[str, list[dict]], SampleCheck] = run_samples,
) -> TutorResult:
    warnings: list[str] = []

    # ① ② 修正案とサンプル確認
    fix = generate_fix(generate, problem, code, verdict, runner)
    if fix.check.passed is None:
        warnings.append("保存済みのサンプルがないため、修正コードの確認を飛ばしました")
    elif fix.check.passed is False:
        warnings.append(f"{fix.attempts} 回試しましたが、修正コードはサンプルを通りませんでした")

    # ③ 差分と分岐
    diff, changed, total = compute_diff(code, fix.fixed_code)
    level = classify_level(changed, total, fix.check.passed)

    # ④ 記録帳
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
    )
    past = count_past_same_type(db, fix.mistake_type, exclude_id=log.id)

    # ⑤ ⑥ 似た問題を検索して AC 済み / 未 AC に分ける
    similar = find_similar(searcher, problem.problem_id, body_text, fix.correct_idea, warnings)
    solved = solved_problem_ids(db, username)
    reference = [p for p in similar if p.problem_id in solved]
    next_problems = [p for p in similar if p.problem_id not in solved]

    # ⑦ 最終解説（公式解説の本文は渡さない）
    prompt = build_explanation_prompt(
        problem, code, fix.fixed_code, diff, fix.gap_summary, fix.correct_idea,
        fix.mistake_type, past, similar,
    )
    explanation = generate(prompt, EXPLANATION_SCHEMA).get("explanation", "")
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = ""
        warnings.append("解説の生成に失敗しました（LLM の出力が空でした）")

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
    )
