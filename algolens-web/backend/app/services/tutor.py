"""RAG 家庭教師: 提出コードから赤ペン（最小修正）・別解・ずれの解説・似た問題を返す（docs/rag-tutor-design.md）。

流れ（explain）:
  1. LLM 1 回目で次をまとめて JSON で受け取る
     - ① 赤ペン: 元のコードへの変更の一覧（行番号・元の行・新しい行・理由）と、計算量・計算回数の目安
     - ② 別解: もっと簡単な解き方があれば（①の代わりにはしない）
     - 確認用コード（愚直解・小さい入力を作るコード・最大サイズの入力を作るコード）。
       問題ごとに保存し、保存済みなら頼まない
  2. 赤ペンを元のコードに当てて確かめ、だめなら落ちた確認を伝えて 1 をやり直す（最大 2 回）
     赤ペンの指定 → 変更の大きさ（半分を超えたら書き直しとみなす）→ 計算回数の目安 → サンプル
     → 愚直解との比較 → 最大サイズの入力 の順
     最後までだめなら「少ない修正では直せない」とし、「考え方」に分ける
  3. 別解はサンプルと最大サイズの入力で確かめ、通ったときだけ出す
  4. 差分の大きさ（コメント・空行を除く）で「書き方」「考え方」に分ける
  5. mistake_logs に保存し、同じミスの種類の過去回数を数える
  6. 公式解説ストアを 2 通りの文章で検索する（本問は除く）
  7. AC 済みなら「参考」、未 AC なら「次に解く問題」に分ける
  8. LLM 2 回目で解説を生成する（公式解説の本文は渡さない）

LLM・検索・AC 判定・確認の実行は引数で差し替えられるようにして、テストでは偽物を渡す。
"""

import difflib
import json
import math
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Callable, Protocol, Sequence

from bs4 import BeautifulSoup
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.mistake_log import FIX_CONFIRMED, FIX_FAILED, MISTAKE_LEVELS, MISTAKE_TYPES, MistakeLog
from app.services.checkers import (  # noqa: F401  run_samples などは従来どおりここからも使える
    BRUTE_MISMATCH,
    BRUTE_SKIPPED,
    DEFAULT_TIME_LIMIT_SEC,
    SAMPLE_TIME_LIMIT_SEC,
    STRESS_OK,
    STRESS_SKIPPED,
    STRESS_TLE,
    BruteCases,
    BruteCheck,
    CaseResult,
    CheckerStore,
    MemoryCheckerStore,
    ProblemCheckers,
    SampleCheck,
    StressCheck,
    check_generator,
    compare_with_brute,
    find_pypy,
    outputs_match,
    prepare_brute_cases,
    run_samples,
    run_stress,
)
from app.services.editorial_scraper import EDITORIALS_DIR, load_meta, problem_dir
from app.services.redpen import Edit, EditError, apply_edits, format_edits, parse_edits

MAX_RETRIES = 2              # 1 回目に加えてやり直す回数
OPS_LIMIT = 10**9            # 計算回数の目安がこれ（10^8 の 10 倍）を超えたら実行せずに作り直す
MAX_GENERATORS = 3           # 最大サイズの入力を作るコードの数
SUBMIT_VERDICTS = ("AC", "WA", "TLE", "RE")
SMALL_DIFF_MAX_LINES = 3     # 変更がこの行数以下なら「書き方」
SMALL_DIFF_MAX_RATIO = 0.2   # 変更が元コードのこの割合以下なら「書き方」
SIMILAR_K = 3
_STATEMENT_MAX_CHARS = 6000

# 作り直しの記録で使う、落ちた確認の名前
CHECK_FORMAT = "出力形式"
CHECK_EDITS = "赤ペンの指定"
CHECK_SIZE = "変更の大きさ"
CHECK_OPS = "計算回数"
CHECK_SAMPLES = "サンプル"
CHECK_BRUTE = "愚直解との比較"
CHECK_STRESS = "最大サイズ"


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


def _is_code_line(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def compute_diff(original: str, fixed: str) -> tuple[str, int, int]:
    """unified diff の文字列・変更行数・元コードの行数を返す。

    行数はコメントだけの行と空行を除いて数える（diff の文字列にはそれらも含める）。
    変更行数は赤ペンで書く量: 置き換え・追加は新しく書いた行の数、削除だけの箇所は消した行の数。
    （入れ子をほどいて数行を消し 1 行にまとめた場合も、書いたのは 1 行と数える）
    1 行だけ書き換えた場合は 1 行と数える。行末の空白と改行コードの違いは無視する。
    """
    a, b = _normalize_lines(original), _normalize_lines(fixed)
    a_code, b_code = [x for x in a if _is_code_line(x)], [x for x in b if _is_code_line(x)]
    changed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a_code, b_code, autojunk=False).get_opcodes():
        if tag != "equal":
            changed += (j2 - j1) if j2 > j1 else (i2 - i1)
    diff = "\n".join(
        difflib.unified_diff(a, b, fromfile="original", tofile="fixed", lineterm="")
    )
    return diff, changed, len(a_code)


def classify_level(changed_lines: int, total_lines: int, samples_passed: bool | None) -> str:
    """確認を通らなければ「考え方」。通った（または未確認）なら差分の大きさで判定する。"""
    if samples_passed is False:
        return "考え方"
    if changed_lines <= SMALL_DIFF_MAX_LINES:
        return "書き方"
    if total_lines > 0 and changed_lines / total_lines <= SMALL_DIFF_MAX_RATIO:
        return "書き方"
    return "考え方"


def is_rewrite(changed_lines: int, total_lines: int) -> bool:
    """赤ペンとして大きすぎる（コメント・空行を除く行の半分を超えて変えた）か。"""
    return changed_lines > SMALL_DIFF_MAX_LINES and changed_lines * 2 > total_lines


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

_EDIT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "line": {"type": "INTEGER"},
        "action": {"type": "STRING", "enum": ["replace", "delete", "insert_after"]},
        "original": {"type": "STRING"},
        "new": {"type": "STRING"},
        "reason": {"type": "STRING"},
    },
    "required": ["line", "action", "original", "new", "reason"],
}


def first_pass_schema(ask_alternative: bool, need_brute: bool, need_max: bool) -> dict:
    """LLM 1 回目の JSON の形。別解・確認用コードは要るときだけ頼む。"""
    props = {
        "edits": {"type": "ARRAY", "items": _EDIT_SCHEMA},
        "gap_summary": {"type": "STRING"},
        "mistake_type": {"type": "STRING", "enum": list(MISTAKE_TYPES)},
        "lesson": {"type": "STRING"},
        "correct_idea": {"type": "STRING"},
        "complexity": {"type": "STRING"},
        "estimated_ops": {"type": "NUMBER"},
    }
    if ask_alternative:
        props |= {
            "alternative_code": {"type": "STRING"},
            "alternative_complexity": {"type": "STRING"},
            "alternative_reason": {"type": "STRING"},
        }
    if need_brute:
        props |= {"brute_code": {"type": "STRING"}, "small_input_generator": {"type": "STRING"}}
    if need_max:
        props["max_input_generators"] = {"type": "ARRAY", "items": {"type": "STRING"}}
    return {"type": "OBJECT", "properties": props, "required": list(props)}


EXPLANATION_SCHEMA = {
    "type": "OBJECT",
    "properties": {"explanation": {"type": "STRING"}},
    "required": ["explanation"],
}

# Gemini には学習者本人の言葉で頼み、文章中で学習者を「あなた」と呼ばせる
ADDRESS_RULE = "文章はすべて日本語で書き、私のことは「あなた」と呼んでください（「生徒」「生徒さん」とは書かない）。"

# 確認用コードの頼み方（AC の提案でも使う）
MAX_GENERATORS_SPEC = f"""- max_input_generators: 制約の上限ちょうどの大きさの入力を 1 つ標準出力に書く Python コードを 1〜{MAX_GENERATORS} 個
  - 形の違う入力にする（例: ランダム / 整列済み / 同じ値ばかり / 素朴な解き方が遅くなる形）
  - 入力形式と制約を必ず守る。乱数は random.seed(0) で固定する。標準入力は読まない。コードブロック記号は付けない"""
_BRUTE_SPEC = """- brute_code: 制約は無視してよいので、小さい入力で確実に正しい答えを出す素朴な Python コード（全探索など）。
  標準入力から読み標準出力に書く。コードブロック記号は付けない
- small_input_generator: sys.argv[1] を乱数の種にして、制約を満たす小さい入力を 1 つ標準出力に書く Python コード
  - 大きさは brute_code がすぐ終わる程度（N は 1〜8 くらい）。値の範囲も小さくして、答えが偏らないようにする
  - 標準入力は読まない。コードブロック記号は付けない"""


def number_lines(code: str) -> str:
    """プロンプト用に "  3| print(x)" の形で行番号を付ける。"""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    width = len(str(len(lines)))
    return "\n".join(f"{i:>{width}}| {line}" for i, line in enumerate(lines, 1))


def build_first_prompt(
    problem: ProblemData,
    code: str,
    verdict: str,
    feedback: str = "",
    previous_failure: str = "",
    ask_alternative: bool = True,
    need_brute: bool = False,
    need_max: bool = False,
    counterexample: str = "",
) -> str:
    """previous_failure: 前回の修正版を提出して通らなかったときの内容（やり直しのたびに渡す）。
    counterexample: 元のコードが愚直解と違う答えを出した小さい入力（あればバグの場所の手がかりにする）。
    """
    previous = f"\n## 前回の修正版を提出した結果\n{previous_failure}\n" if previous_failure else ""
    if counterexample:
        previous += f"\n## 私のコードが間違える小さい入力（愚直解と比べて見つけたもの）\n{counterexample}\n"
    retry = f"\n## 前回の赤ペンの問題点\n{feedback}\nこれを踏まえて赤ペンを直してください。\n" if feedback else ""
    tasks = ["① 赤ペン: 私のコードの考え方を残したまま、間違っている行だけを直す変更の一覧"]
    outputs = []
    if ask_alternative:
        tasks.append("② 別解: もっと簡単な解き方・考え方があれば、①とは別に（①の代わりにはしない）")
        outputs.append(
            "- alternative_code: 別解の Python コード全体（なければ空文字。コードブロック記号は付けない）\n"
            "- alternative_complexity: 別解の時間計算量（なければ空文字）\n"
            "- alternative_reason: 別解がどう簡単か（Markdown で簡潔に。なければ空文字）"
        )
    if need_brute or need_max:
        tasks.append("③ 答えを確かめるためのコード（下の出力の説明を参照）")
    if need_brute:
        outputs.append(_BRUTE_SPEC)
    if need_max:
        outputs.append(MAX_GENERATORS_SPEC)
    extra = ("\n" + "\n".join(outputs)) if outputs else ""
    task_lines = "\n".join(tasks)
    return f"""AtCoder の家庭教師として答えてください。私の Python 提出コードが {verdict} になりました。
{ADDRESS_RULE}

## お願い
{task_lines}

## 赤ペンの決まり（最重要）
- 私のコードの考え方・構造・変数名を残し、バグの原因の行だけを直す。全体の書き直しは禁止
- まず「私の考え方のままで、どの行をどう変えれば正しくなるか」を考える。
  初期値を変える・不等号を変える・分岐の中身を差し替える・条件を 1 つ足す、のような小さな直しを優先する
- 変える行（コメント・空行を除く）は元のコードの半分以下にする。超えると書き直しとみなして受け付けない
- 変更は edits の一覧で表す。下のコードの行番号を使う
  - action "replace": line の行を new に置き換える（original にはその行の元の内容）。
    new は複数行でもよい（1 行を数行のブロックに置き換えられる）
  - action "delete": line の行を消す（original にはその行の元の内容、new は空文字）
  - action "insert_after": line の行の後に new を入れる（先頭なら line は 0、original は空文字）
  - new はインデントも含めて書く。複数行なら改行で区切る
  - reason: なぜ直すかを短く
- 空行とコメントの行は edits の対象にしない（そのまま残す）。内容を変えない replace も書かない
- 直す行が少ないほど良い。使わなくなった行も、動作に影響しなければ残してよい
- 制約の上限の入力でも制限時間（{problem.time_limit_sec:g} 秒）に間に合うこと

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 私のコード（判定: {verdict}。各行の先頭は行番号）
```
{number_lines(code)}
```
{previous}{retry}
## 出力（JSON）
- edits: ① 赤ペンの変更の一覧（上の決まりのとおり）
- gap_summary: 私の考えと正解のずれを一文で（直した行番号を含める）
- mistake_type: 次から 1 つ: {", ".join(MISTAKE_TYPES)}
- lesson: 次に同じミスをしないための教訓を一文で
- correct_idea: この問題を解く正しい考え方を一文で（使う手法名があれば手法名を含める）
- complexity: 赤ペンで直したコードの時間計算量（例: "O(N log N)"）
- estimated_ops: 制約の上限での、赤ペンで直したコードの計算回数の目安（数値。例: N=2×10^5 で O(N log N) なら 3600000）{extra}
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
    fix_found: bool = True,
    alternative: "Alternative | None" = None,
) -> str:
    similar_lines = "\n".join(f"- {p.problem_id}: {p.title}" for p in similar) or "- なし"
    status = "" if fix_found else (
        "\n※ 少ない修正（赤ペン）では確認を通せませんでした。下の赤ペン案は正しくない可能性があるので、"
        "どこがずれているかと正しい考え方を中心に説明してください。\n"
    )
    alt = (
        f"\n## 別解（サンプルと最大サイズの入力で確認済み。計算量 {alternative.complexity or '不明'}）\n"
        f"{alternative.reason}\n"
        if alternative else ""
    )
    alt_item = "\n  5. 別解があれば、赤ペンとの違いを一言（別解は赤ペンの代わりではない）" if alternative else ""
    return f"""AtCoder の家庭教師として、私の提出コードについて最終的な解説を書いてください。
{ADDRESS_RULE}
{status}
## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 私のコード
```python
{code}
```

## 赤ペンで直したコード
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
- 赤ペン版の計算量: {complexity or "不明"}
- ミスの種類: {mistake_type}（この種類のミスは過去に {past_count} 回）
{alt}
## 似た問題（問題IDとタイトルのみ）
{similar_lines}

## 出力（JSON）
- explanation: Markdown の解説。次の順で簡潔に。
  1. どこがずれていたか（差分の行を指して）
  2. 正しい考え方
  3. 同じミスを繰り返さないためのチェックポイント（過去の回数に触れる）
  4. 似た問題で何を確かめるとよいか（問題IDを挙げる。中身は推測で書かない）{alt_item}
"""


def _strip_code_fence(code: str) -> str:
    m = re.match(r"^\s*```[a-zA-Z0-9]*\n(.*?)\n?```\s*$", code, re.DOTALL)
    return m.group(1) if m else code


def _code_field(data: dict, key: str) -> str:
    value = data.get(key)
    return _strip_code_fence(value).strip() + "\n" if isinstance(value, str) and value.strip() else ""


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


def _counterexample(code: str, brute_cases: BruteCases | None, checks: "Checks") -> str:
    """元のコードを愚直解の入力で実行し、最初に答えが違った入力を説明する文（なければ空文字）。"""
    if brute_cases is None:
        return ""
    result = checks.compare_brute(code, brute_cases)
    if result.status != BRUTE_MISMATCH:
        return ""
    fail = result.failure
    msg = f"入力:\n{fail.input}\n正しい答え:\n{fail.expected}\n"
    if fail.status == "WA":
        msg += f"私のコードの答え:\n{fail.actual}\n"
    else:
        msg += f"私のコードは {fail.status} になりました。\n"
    return msg


def _brute_feedback(brute: BruteCheck) -> str:
    fail = brute.failure
    msg = f"小さい入力で愚直解（全探索）と答えが違いました（{brute.total} 件目、判定 {fail.status}）。\n入力:\n{fail.input}\n愚直解の答え:\n{fail.expected}\n"
    if fail.status == "WA":
        msg += f"赤ペン版の答え:\n{fail.actual}\n"
    if fail.status == "RE":
        msg += f"エラー:\n{fail.stderr[-800:]}\n"
    return msg


STRESS_TLE_FEEDBACK = "最大サイズの入力で時間切れ。計算量を改善して。"


def _ops_feedback(ops: float, complexity: str) -> str:
    return (
        f"計算量 {complexity or '（不明）'} で、制約の上限での計算回数の目安が {ops:.1e} 回です。"
        "10^8 を大きく超えていて間に合いません。計算量を改善して。"
    )


# ---------------------------------------------------------------------------
# 赤ペンと確認
# ---------------------------------------------------------------------------

# (prompt, response_schema) -> 解析済み JSON
Generate = Callable[[str, dict], dict]
Runner = Callable[[str, list[dict]], SampleCheck]
# (コード, generator の一覧, 問題の制限時間) -> StressCheck
StressRunner = Callable[[str, list[str], float], StressCheck]


@dataclass
class Checks:
    """確認の実行方法と、確認用コードの保存先（テストでは差し替える）。"""

    runner: Runner = run_samples
    stress: StressRunner = run_stress
    prepare_brute: Callable[[str, str], BruteCases] = prepare_brute_cases
    compare_brute: Callable[[str, BruteCases], BruteCheck] = compare_with_brute
    check_generator: Callable[[str], str] = check_generator
    store: CheckerStore = field(default_factory=MemoryCheckerStore)


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
class Attempt:
    """1 回分の赤ペンの記録。failed が None なら全部の確認を通った。"""

    attempt: int
    failed: str | None
    detail: str = ""


@dataclass(frozen=True)
class RedPen:
    edits: list[Edit]
    fixed_code: str
    gap_summary: str
    mistake_type: str
    lesson: str
    correct_idea: str
    complexity: str
    estimated_ops: float | None   # LLM が数値を返さなければ None
    check: SampleCheck
    brute: BruteCheck | None = None    # 実行しなかったら None
    stress: StressCheck | None = None  # 実行しなかったら None
    ops_too_large: bool = False


@dataclass(frozen=True)
class Alternative:
    code: str
    complexity: str
    reason: str
    check: SampleCheck
    stress: StressCheck


@dataclass(frozen=True)
class FixOutcome:
    redpen: RedPen
    fix_found: bool              # 赤ペンが全部の確認を通ったか
    attempts: int
    attempt_log: list[Attempt]
    alternative: Alternative | None
    notes: list[str]             # 確認用コード・別解についての警告


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


def _parse_analysis(data: dict) -> dict | None:
    """赤ペン以外の分析項目。必須の項目が欠けていれば None。"""
    keys = ("gap_summary", "mistake_type", "lesson", "correct_idea")
    if not all(isinstance(data.get(k), str) and data[k].strip() for k in keys):
        return None
    if data["mistake_type"] not in MISTAKE_TYPES:
        return None
    complexity = data.get("complexity")
    return {k: data[k].strip() for k in keys} | {
        "complexity": complexity.strip() if isinstance(complexity, str) else "",
        "estimated_ops": _parse_ops(data.get("estimated_ops")),
    }


def _absorb_checkers(
    data: dict, problem: ProblemData, checkers: ProblemCheckers, checks: Checks, notes: list[str]
) -> BruteCases | None:
    """LLM が出した確認用コードを確かめ、使えるものを保存する。新しく使えるようになった愚直解の入力を返す。"""
    changed = False
    brute_cases = None
    if not checkers.has_brute:
        brute, small = _code_field(data, "brute_code"), _code_field(data, "small_input_generator")
        if brute and small:
            if checks.runner(brute, problem.samples).passed is False:
                notes.append("愚直解がサンプルを通らなかったため、愚直解との比較には使いません")
            else:
                cases = checks.prepare_brute(brute, small)
                if cases.note:
                    notes.append(f"愚直解との比較の準備に失敗しました: {cases.note}")
                else:
                    checkers.brute_code, checkers.small_generator = brute, small
                    brute_cases, changed = cases, True
    if not checkers.max_generators:
        raw = data.get("max_input_generators")
        gens = [_code_field({"g": g}, "g") for g in raw] if isinstance(raw, list) else []
        ok = []
        for k, g in enumerate([g for g in gens if g][:MAX_GENERATORS], 1):
            error = checks.check_generator(g)
            if error:
                notes.append(f"最大サイズの入力を作るコード {k} は使えませんでした: {error}")
            else:
                ok.append(g)
        if ok:
            checkers.max_generators, changed = ok, True
    if changed:
        checks.store.save(problem.problem_id, checkers)
    return brute_cases


def _verify_redpen(
    code: str,
    data: dict,
    analysis: dict,
    problem: ProblemData,
    checkers: ProblemCheckers,
    brute_cases: BruteCases | None,
    checks: Checks,
) -> tuple[RedPen | None, str | None, str, str]:
    """赤ペンを当てて確かめる。(結果, 落ちた確認, 作り直しの依頼文, 記録用の短い説明) を返す。

    赤ペンの指定 → 変更の大きさ → 計算回数の目安 → サンプル → 愚直解との比較 → 最大サイズの入力
    の順に確かめ、だめな時点で止める。落ちた確認が None なら全部通った。
    """
    try:
        edits = parse_edits(data.get("edits"))
        fixed = apply_edits(code, edits)
    except EditError as e:
        return None, CHECK_EDITS, str(e), str(e)
    previous = f"\n前回の赤ペン:\n{format_edits(edits)}"
    base = dict(edits=edits, fixed_code=fixed, **analysis)

    _, changed, total = compute_diff(code, fixed)
    if is_rewrite(changed, total):
        pen = RedPen(**base, check=SampleCheck(passed=None))
        feedback = (
            f"変更が大きすぎます（コメント・空行を除く {total} 行中 {changed} 行を変更）。これは書き直しです。"
            f"私のコードの考え方を残し、間違っている行だけを直してください（変更は {total // 2} 行以下）。"
        )
        return pen, CHECK_SIZE, feedback + previous, f"{total} 行中 {changed} 行を変更"

    ops = analysis["estimated_ops"]
    if ops is not None and ops > OPS_LIMIT:
        pen = RedPen(**base, check=SampleCheck(passed=None), ops_too_large=True)
        return pen, CHECK_OPS, _ops_feedback(ops, analysis["complexity"]) + previous, f"目安 {ops:.1e} 回"

    check = checks.runner(fixed, problem.samples)
    if check.passed is False:
        fail = check.first_failure()
        return (RedPen(**base, check=check), CHECK_SAMPLES, _failure_feedback(check) + previous,
                f"サンプル {fail.index} が {fail.status}")

    brute = checks.compare_brute(fixed, brute_cases) if brute_cases is not None else None
    if brute is not None and brute.status == BRUTE_MISMATCH:
        return (RedPen(**base, check=check, brute=brute), CHECK_BRUTE, _brute_feedback(brute) + previous,
                f"小さい入力 {brute.total} 件目で {brute.failure.status}")

    stress = checks.stress(fixed, checkers.max_generators, problem.time_limit_sec) if checkers.max_generators else None
    pen = RedPen(**base, check=check, brute=brute, stress=stress)
    if stress is not None and stress.status == STRESS_TLE:
        return pen, CHECK_STRESS, STRESS_TLE_FEEDBACK + previous, f"{stress.time_limit:g} 秒で時間切れ（{stress.interpreter}）"
    return pen, None, "", ""


def _check_alternative(
    data: dict, problem: ProblemData, checkers: ProblemCheckers, checks: Checks, notes: list[str]
) -> Alternative | None:
    """別解をサンプルと最大サイズの入力で確かめ、通ったときだけ返す（愚直解との比較はしない）。"""
    code = _code_field(data, "alternative_code")
    if not code:
        return None
    check = checks.runner(code, problem.samples)
    if check.passed is not True:
        notes.append("別解はありましたが、サンプルを通らなかったため出していません")
        return None
    if not checkers.max_generators:
        notes.append("別解はありましたが、最大サイズの入力で確かめられなかったため出していません")
        return None
    stress = checks.stress(code, checkers.max_generators, problem.time_limit_sec)
    if stress.status != STRESS_OK:
        reason = "時間切れになった" if stress.status == STRESS_TLE else "確かめられなかった"
        notes.append(f"別解はありましたが、最大サイズの入力で{reason}ため出していません")
        return None
    return Alternative(
        code=code,
        complexity=str(data.get("alternative_complexity") or "").strip(),
        reason=str(data.get("alternative_reason") or "").strip(),
        check=check,
        stress=stress,
    )


def generate_fix(
    generate: Generate,
    problem: ProblemData,
    code: str,
    verdict: str,
    checks: Checks | None = None,
    previous_failure: str = "",
) -> FixOutcome:
    """LLM 1 回目（赤ペン・別解・確認用コード）+ 確認。だめなら落ちた確認を伝えて最大 MAX_RETRIES 回やり直す。

    別解は 1 回目の応答のものだけ使う。確認用コードは保存済みなら頼まず、足りないものだけ頼む。
    """
    checks = checks or Checks()
    notes: list[str] = []
    checkers = checks.store.load(problem.problem_id)
    brute_cases = None
    if checkers.has_brute:
        brute_cases = checks.prepare_brute(checkers.brute_code, checkers.small_generator)
        if brute_cases.note:
            notes.append(f"保存済みの愚直解で比較の準備に失敗しました: {brute_cases.note}")
            brute_cases = None
    # 元のコードが間違える小さい入力。愚直解がまだなければ、1 回目の応答で得てから求める
    counterexample = _counterexample(code, brute_cases, checks)

    feedback = ""
    last: RedPen | None = None
    last_analysis: dict | None = None
    first_data: dict | None = None
    log: list[Attempt] = []
    found = False
    for attempt in range(1, MAX_RETRIES + 2):
        need_brute, need_max = not checkers.has_brute, not checkers.max_generators
        prompt = build_first_prompt(
            problem, code, verdict, feedback, previous_failure,
            ask_alternative=attempt == 1, need_brute=need_brute, need_max=need_max,
            counterexample=counterexample,
        )
        data = generate(prompt, first_pass_schema(attempt == 1, need_brute, need_max))
        if attempt == 1:
            first_data = data
        if need_brute or need_max:
            absorbed = _absorb_checkers(data, problem, checkers, checks, notes)
            if absorbed is not None:
                brute_cases = absorbed
                counterexample = _counterexample(code, brute_cases, checks)

        analysis = _parse_analysis(data)
        if analysis is None:
            feedback = "出力の JSON に必要な項目が欠けているか、mistake_type が選択肢にありませんでした。"
            log.append(Attempt(attempt, CHECK_FORMAT, "必要な項目が欠けていた"))
            continue
        last_analysis = analysis
        pen, failed, feedback, detail = _verify_redpen(code, data, analysis, problem, checkers, brute_cases, checks)
        log.append(Attempt(attempt, failed, detail))
        if pen is not None:
            last = pen
        if failed is None:
            found = True
            break

    if last_analysis is None:
        raise TutorError("LLM から有効な赤ペンを得られませんでした")
    if last is None:
        # 赤ペンを一度も元のコードに当てられなかった。元のコードのまま記録する
        last = RedPen(edits=[], fixed_code=code, **last_analysis, check=SampleCheck(passed=None))
    if last.edits and last.check.passed is None and not last.check.cases:
        # 実行する前の確認（目安・変更の大きさ）で止まった。サンプルの結果だけは表示できるよう取っておく
        last = replace(last, check=checks.runner(last.fixed_code, problem.samples))

    alternative = _check_alternative(first_data or {}, problem, checkers, checks, notes)
    return FixOutcome(
        redpen=last, fix_found=found, attempts=len(log), attempt_log=log, alternative=alternative, notes=notes,
    )


def _verification_warnings(outcome: FixOutcome) -> list[str]:
    pen = outcome.redpen
    warnings = []
    if pen.check.passed is None and not pen.ops_too_large and pen.edits:
        warnings.append("保存済みのサンプルがないため、サンプルでの確認を飛ばしました")
    if pen.estimated_ops is None:
        warnings.append("計算回数の目安を得られなかったため、目安での確認を飛ばしました")
    if pen.brute is not None and pen.brute.status == BRUTE_SKIPPED:
        warnings.append(f"愚直解との比較を飛ばしました: {pen.brute.note}")
    if pen.stress is not None and pen.stress.status == STRESS_SKIPPED:
        warnings.append(f"最大サイズの入力での確認を飛ばしました: {pen.stress.note}")
    elif pen.stress is not None and pen.stress.note:
        warnings.append(f"最大サイズの入力の一部を飛ばしました: {pen.stress.note}")
    return warnings + outcome.notes


# ---------------------------------------------------------------------------
# 似た問題
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------

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
    brute: BruteCheck | None = None
    fix_found: bool = True
    edits: list[Edit] = field(default_factory=list)
    attempt_log: list[Attempt] = field(default_factory=list)
    alternative: Alternative | None = None


def explain(
    db: Session,
    generate: Generate,
    searcher: Searcher | None,
    problem: ProblemData,
    code: str,
    verdict: str,
    body_text: str,
    username: str | None = None,
    generate_first: Generate | None = None,
    checks: Checks | None = None,
    retry_of: MistakeLog | None = None,
) -> TutorResult:
    """generate_first を渡すと、LLM 1 回目（赤ペン）だけそちらを使う。

    retry_of を渡すと、その記録の修正版を提出して通らなかったものとして作り直す。
    """
    warnings: list[str] = []
    previous_failure = ""
    if retry_of is not None:
        previous_failure = resubmit_feedback(retry_of)
        warnings.append(f"前回の修正版は提出して {retry_of.submitted_verdict} だったため、作り直した修正版です")

    # ① ② 赤ペン・別解と確認
    outcome = generate_fix(generate_first or generate, problem, code, verdict, checks, previous_failure)
    pen = outcome.redpen
    warnings.extend(_verification_warnings(outcome))

    # ④ 差分と分岐（赤ペンで直せなかったら「考え方」）
    diff, changed, total = compute_diff(code, pen.fixed_code)
    level = classify_level(changed, total, pen.check.passed if outcome.fix_found else False)

    # ⑤ 同じミスの過去回数（記録の保存は最後に行う）
    past = count_past_same_type(db, pen.mistake_type)

    # ⑥ ⑦ 似た問題を検索して AC 済み / 未 AC に分ける
    similar = find_similar(searcher, problem.problem_id, body_text, pen.correct_idea, warnings)
    reference, next_problems = split_by_solved(db, similar, username)

    # ⑧ 最終解説（公式解説の本文は渡さない）
    prompt = build_explanation_prompt(
        problem, code, pen.fixed_code, diff, pen.gap_summary, pen.correct_idea,
        pen.mistake_type, past, similar, pen.complexity, outcome.fix_found, outcome.alternative,
    )
    explanation = generate(prompt, EXPLANATION_SCHEMA).get("explanation", "")
    if not isinstance(explanation, str) or not explanation.strip():
        explanation = ""
        warnings.append("解説の生成に失敗しました（LLM の出力が空でした）")

    # ⑤ 記録帳: 途中で LLM が失敗したときに記録だけ残らないよう、すべて揃ってから保存する
    log = save_mistake_log(
        db,
        problem_id=problem.problem_id,
        original_code=code,
        fixed_code=pen.fixed_code,
        diff=diff,
        verdict=verdict,
        diff_lines=changed,
        mistake_level=level,
        mistake_type=pen.mistake_type,
        samples_passed=pen.check.passed,
        gap_summary=pen.gap_summary,
        correct_idea=pen.correct_idea,
        lesson=pen.lesson,
        retry_of_id=retry_of.id if retry_of is not None else None,
        fix_found=outcome.fix_found,
        edits=json.dumps([asdict(e) for e in pen.edits], ensure_ascii=False),
        attempt_log=json.dumps([asdict(a) for a in outcome.attempt_log], ensure_ascii=False),
    )

    return TutorResult(
        log=log,
        total_lines=total,
        sample_cases=pen.check.cases,
        attempts=outcome.attempts,
        past_same_type_count=past,
        reference=reference,
        next_problems=next_problems,
        explanation=explanation,
        warnings=warnings,
        complexity=pen.complexity,
        estimated_ops=pen.estimated_ops,
        stress=pen.stress,
        brute=pen.brute,
        fix_found=outcome.fix_found,
        edits=pen.edits,
        attempt_log=outcome.attempt_log,
        alternative=outcome.alternative,
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
    赤ペンで直せなかった記録には、提出する修正版がないので記録できない。
    """
    if submitted not in SUBMIT_VERDICTS:
        raise ValueError(f"提出結果が選択肢にありません: {submitted}")
    if log.fix_found is False:
        raise TutorError("この記録は少ない修正で直せなかったため、提出する修正版がありません")
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
