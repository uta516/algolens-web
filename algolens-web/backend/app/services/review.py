"""振り返り: コンテストの最後の提出を問題ごとに取り込み、判定に応じて家庭教師の処理を行う。

流れ:
  plan_contest   提出一覧から問題ごとに最後の提出を選び、tutor_reports に pending で作る
                 （同じ提出の行が既にあれば作らない）
  process_report pending の行を 1 問ずつ処理して done にする（done の行は作り直さない）
                 - WA / TLE / RE: 家庭教師（tutor.explain）と同じ流れ
                 - AC: 計算量が良くなる / 行数が半分以下になる解き方だけ提案し、サンプルで確かめる
                 - それ以外（CE、Python 以外の言語など）: 対象外

1 問ごとにコミットするので、途中で止まっても pending の行から再開できる。
外部アクセス（AtCoder・Gemini・解説ストア）と提出コードの取得は ReviewDeps で差し替えられる。
提出コードは手元のフォルダか画面での貼り付けで用意する（提出ページは robots.txt で禁止）。
"""

import calendar
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.mistake_log import MistakeLog
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.tutor_report import (
    KIND_AC,
    KIND_MISTAKE,
    KIND_SKIPPED,
    REPORT_DONE,
    REPORT_PENDING,
    TutorReport,
)
from app.models.user import User
from app.services.atcoder_fetcher import normalize_submission
from app.services.editorial_scraper import (
    EDITORIALS_DIR,
    AtCoderClient,
    TargetProblem,
    fetch_and_save_problem,
    load_meta,
    refresh_editorials,
)
from app.services.tutor import (
    Generate,
    ProblemData,
    ADDRESS_RULE,
    SampleCheck,
    Searcher,
    StressRunner,
    TutorResult,
    compute_diff,
    explain,
    find_similar,
    load_problem,
    number_lines,
    run_samples,
    run_stress,
    split_by_solved,
    _strip_code_fence,
)

MISTAKE_VERDICTS = ("WA", "TLE", "RE")


class ReviewError(Exception):
    """1 問の処理を続けられなかったときの例外（行は pending のまま残る）。"""


class CodeRequired(ReviewError):
    """提出コードが手元のフォルダになく、画面での貼り付けが必要なとき。"""


# ---------------------------------------------------------------------------
# 最後の提出の選び方
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewTarget:
    problem_id: str
    problem_index: str
    submission_id: int
    verdict: str
    language: str
    submitted_at: int
    wa_count: int  # 最後の提出より前の WA / TLE / RE の回数


def problem_index_of(problem_id: str) -> str:
    """"abc420_c" → "C"。古い ABC の "abc001_1" 形式は "A" にする。"""
    suffix = problem_id.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return chr(ord("A") + int(suffix) - 1)
    return suffix.upper()


def select_last_submissions(submissions: list[dict], contest_id: str) -> list[ReviewTarget]:
    """コンテストの提出から、問題ごとに一番最後の提出を 1 つ選び、問題順に並べて返す。

    「最後」は提出時刻、同時刻なら提出 ID の大きい方。
    WA 回数は、その問題で最後の提出より前にあった WA / TLE / RE の数。
    """
    by_problem: dict[str, list[dict]] = {}
    for sub in submissions:
        if sub.get("contest_id") == contest_id:
            by_problem.setdefault(sub["problem_id"], []).append(sub)

    targets = []
    for problem_id, subs in by_problem.items():
        subs.sort(key=lambda s: (s["epoch_second"], s["id"]))
        last = subs[-1]
        wa_count = sum(1 for s in subs[:-1] if s.get("result") in MISTAKE_VERDICTS)
        targets.append(ReviewTarget(
            problem_id=problem_id,
            problem_index=problem_index_of(problem_id),
            submission_id=int(last["id"]),
            verdict=last.get("result", ""),
            language=last.get("language", ""),
            submitted_at=int(last["epoch_second"]),
            wa_count=wa_count,
        ))
    return sorted(targets, key=lambda t: (t.problem_index, t.problem_id))


def is_python(language: str) -> bool:
    lang = language.lower()
    return "python" in lang or "pypy" in lang


def classify_kind(verdict: str, language: str) -> tuple[str, str]:
    """(kind, 対象外の理由) を返す。サンプル実行は Python なので、他の言語は対象外にする。"""
    if verdict not in MISTAKE_VERDICTS and verdict != "AC":
        return KIND_SKIPPED, f"{verdict} は対象外です"
    if not is_python(language):
        return KIND_SKIPPED, f"Python 以外の提出（{language}）は対象外です"
    return (KIND_AC if verdict == "AC" else KIND_MISTAKE), ""


# ---------------------------------------------------------------------------
# 取り込み（pending 行の作成）
# ---------------------------------------------------------------------------

def latest_reports(db: Session, username: str, contest_id: str) -> list[TutorReport]:
    """保存済みの行のうち、問題ごとに最後の提出の行だけを問題順に返す。"""
    rows = db.scalars(
        select(TutorReport).where(
            TutorReport.username == username, TutorReport.contest_id == contest_id
        )
    ).all()
    latest: dict[str, TutorReport] = {}
    for r in rows:
        cur = latest.get(r.problem_id)
        if cur is None or (r.submitted_at, r.submission_id) > (cur.submitted_at, cur.submission_id):
            latest[r.problem_id] = r
    return sorted(latest.values(), key=lambda r: (r.problem_index, r.problem_id))


def plan_contest(
    db: Session,
    username: str,
    contest_id: str,
    submissions: list[dict],
    titles: dict[str, str],
) -> list[TutorReport]:
    """最後の提出ごとに pending の行を作る。同じ提出の行が既にあれば作らない。"""
    targets = select_last_submissions(submissions, contest_id)
    ids = [t.submission_id for t in targets]
    existing = set(db.scalars(select(TutorReport.submission_id).where(TutorReport.submission_id.in_(ids))).all())

    for t in targets:
        if t.submission_id in existing:
            continue
        kind, _ = classify_kind(t.verdict, t.language)
        db.add(TutorReport(
            username=username,
            contest_id=contest_id,
            problem_id=t.problem_id,
            problem_index=t.problem_index,
            title=titles.get(t.problem_id) or t.problem_index,
            submission_id=t.submission_id,
            verdict=t.verdict,
            language=t.language,
            submitted_at=t.submitted_at,
            wa_count=t.wa_count,
            status=REPORT_PENDING,
            kind=kind,
        ))
    db.commit()
    return latest_reports(db, username, contest_id)


# ---------------------------------------------------------------------------
# 提出データの同期（「参考」= AC 済みの判定を最新にするため）
# ---------------------------------------------------------------------------

def last_synced_epoch(db: Session, username: str) -> int:
    """DB にあるユーザーの最新の提出時刻（epoch 秒）。提出がなければ 0。"""
    stmt = (
        select(func.max(Submission.submitted_at))
        .join(User, User.id == Submission.user_id)
        .where(User.atcoder_username == username)
    )
    latest = db.scalar(stmt)
    # normalize_submission は UTC の naive datetime で保存している
    return calendar.timegm(latest.timetuple()) if latest else 0


def sync_user_submissions(db: Session, username: str, raw_subs: list[dict], problems: list[dict]) -> int:
    """AtCoder Problems API の提出を DB に追加し、追加した件数を返す。

    /sync/submissions と違い、ユーザーや問題が DB になければ作る
    （開催直後のコンテストの問題は、問題一覧の同期前でも提出を取り込めるように）。
    """
    user = db.scalar(select(User).where(User.atcoder_username == username))
    if user is None:
        user = User(atcoder_username=username)
        db.add(user)
        db.flush()

    sids = [s["id"] for s in raw_subs]
    existing = set(db.scalars(
        select(Submission.atcoder_submission_id).where(Submission.atcoder_submission_id.in_(sids))
    ).all()) if sids else set()
    titles = {p["id"]: p.get("title") or p.get("name", "") for p in problems}
    problem_cache: dict[str, Problem] = {}

    inserted = 0
    for raw in raw_subs:
        if raw["id"] in existing:
            continue
        normalized = normalize_submission(raw)
        pid_str = normalized.pop("_atcoder_problem_id")
        problem = problem_cache.get(pid_str) or db.scalar(select(Problem).where(Problem.atcoder_problem_id == pid_str))
        if problem is None:
            problem = Problem(
                atcoder_problem_id=pid_str,
                contest_id=raw["contest_id"].lower(),
                problem_index=raw["problem_id"][-1].upper(),
                title=titles.get(raw["problem_id"], raw["problem_id"]),
                url=f"https://atcoder.jp/contests/{raw['contest_id']}/tasks/{raw['problem_id']}",
            )
            db.add(problem)
            db.flush()
        problem_cache[pid_str] = problem
        db.add(Submission(user_id=user.id, problem_id=problem.id, **normalized))
        existing.add(raw["id"])
        inserted += 1
    db.commit()
    return inserted


# API から提出を取れず、DB にある提出で続けるとき
SYNC_FAILED_WARNING = (
    "提出データを最新にできなかったため、DB にある提出で続けています。"
    "最後の提出や参考の判定が古い可能性があります。時間をおいて取り込み直してください。"
)
# 最新の提出は取れたが、問題一覧が取れず DB に同期できなかったとき
DB_NOT_SYNCED_WARNING = (
    "提出データを DB に同期できなかったため、参考の判定が古い可能性があります。"
    "時間をおいて取り込み直してください。"
)


def db_contest_submissions(db: Session, username: str, contest_id: str) -> list[dict]:
    """DB にあるユーザーのコンテストの提出を、AtCoder Problems API と同じ形の辞書で返す。"""
    rows = db.execute(
        select(Submission, Problem.atcoder_problem_id)
        .join(Problem, Problem.id == Submission.problem_id)
        .join(User, User.id == Submission.user_id)
        .where(User.atcoder_username == username, Problem.contest_id == contest_id)
    ).all()
    prefix = f"{contest_id}_"
    subs = []
    for sub, atcoder_problem_id in rows:
        if sub.atcoder_submission_id is None:
            continue
        # DB の atcoder_problem_id は "{contest_id}_{problem_id}"
        problem_id = atcoder_problem_id[len(prefix):] if atcoder_problem_id.startswith(prefix) else atcoder_problem_id
        subs.append({
            "id": sub.atcoder_submission_id,
            "epoch_second": calendar.timegm(sub.submitted_at.timetuple()),
            "problem_id": problem_id,
            "contest_id": contest_id,
            "result": sub.status,
            "language": sub.language or "",
        })
    return subs


@dataclass(frozen=True)
class GatheredSubmissions:
    submissions: list[dict]
    synced: int          # 今回 DB に追加した提出の件数
    warnings: list[str]


def gather_submissions(
    db: Session,
    username: str,
    contest_id: str,
    fetch_submissions: Callable[[], list[dict]],
    fetch_problems: Callable[[], list[dict]],
) -> GatheredSubmissions:
    """取り込みに使う提出を集め、取れたものは DB に同期する。

    - API から提出を取れなければ、DB にあるそのコンテストの提出で続ける（警告を付ける）。
      DB にも 1 件もなければ ReviewError
    - 提出は取れたが問題一覧が取れず DB に同期できないときも、取れた提出で続ける（警告を付ける）
    """
    try:
        subs = fetch_submissions()
    except httpx.HTTPError as e:
        subs = db_contest_submissions(db, username, contest_id)
        if not subs:
            raise ReviewError(
                f"AtCoder Problems API から提出を取得できず、DB にも {contest_id} の提出がありません: {e}"
            ) from e
        return GatheredSubmissions(subs, 0, [SYNC_FAILED_WARNING])

    try:
        problems = fetch_problems()
    except httpx.HTTPError:
        return GatheredSubmissions(subs, 0, [DB_NOT_SYNCED_WARNING])
    return GatheredSubmissions(subs, sync_user_submissions(db, username, subs, problems), [])


# ---------------------------------------------------------------------------
# AC の提案
# ---------------------------------------------------------------------------

AC_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "current_complexity": {"type": "STRING"},
        "has_better": {"type": "BOOLEAN"},
        "faster": {"type": "BOOLEAN"},
        "better_complexity": {"type": "STRING"},
        "better_code": {"type": "STRING"},
        "current_review": {"type": "STRING"},
        "suggestion_reason": {"type": "STRING"},
        "correct_idea": {"type": "STRING"},
    },
    "required": [
        "current_complexity", "has_better", "faster", "better_complexity",
        "better_code", "current_review", "suggestion_reason", "correct_idea",
    ],
}


def build_ac_prompt(problem: ProblemData, code: str) -> str:
    return f"""AtCoder の家庭教師として答えてください。私の Python 提出コードは AC しました。
{ADDRESS_RULE}
次のどちらかに当てはまる、明らかに良い解き方があるかを判断してください。
  (a) 計算量（オーダー）が良くなる解き方
  (b) コードの行数が今の半分以下になる書き方
どちらにも当てはまらない改善（変数名・書き方の好み・定数倍の高速化など）は提案しないでください。

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 私のコード（各行の先頭は行番号）
```
{number_lines(code)}
```

## 出力（JSON）
- current_complexity: 私のコードの時間計算量（例: "O(N^2)"）
- has_better: (a) か (b) に当てはまる解き方があるか
- faster: 提案が (a) 計算量が良くなるものか
- better_complexity: 提案の時間計算量（提案がなければ空文字）
- better_code: 提案する Python コード全体。標準入力から読み標準出力に書く。コードブロック記号は付けない（なければ空文字）
- current_review: Markdown で簡潔に、私の今の解き方の評価（良い点と計算量）
- suggestion_reason: Markdown で簡潔に、提案がどう良くなるか（行番号を指して。なければ空文字）
- correct_idea: この問題を解く考え方を一文で（使う手法名があれば手法名を含める）
"""


def count_code_lines(code: str) -> int:
    """空行とコメントだけの行を除いた行数。"""
    return sum(1 for line in code.splitlines() if line.strip() and not line.strip().startswith("#"))


def _normalize_complexity(text: str) -> str:
    return "".join(text.split()).lower()


def judge_suggestion(
    original: str,
    better: str,
    faster: bool,
    current_complexity: str,
    better_complexity: str,
) -> str | None:
    """AC の提案を出す基準を満たすなら理由のラベル、満たさなければ None を返す。

    - 計算量が良くなる: LLM が faster とし、かつ計算量の表記が今と違う場合
    - 行数が半分以下: 空行・コメントを除いた行数で比べる（プログラムで判定）
    """
    cur, new = _normalize_complexity(current_complexity), _normalize_complexity(better_complexity)
    if faster and cur and new and cur != new:
        return f"計算量が良くなる（{current_complexity.strip()} → {better_complexity.strip()}）"
    before, after = count_code_lines(original), count_code_lines(better)
    if 0 < after and after * 2 <= before:
        return f"行数が半分以下（{before} 行 → {after} 行）"
    return None


def review_accepted(
    db: Session,
    generate: Generate,
    searcher: Searcher | None,
    problem: ProblemData,
    code: str,
    body_text: str,
    username: str | None = None,
    runner: Callable[[str, list[dict]], SampleCheck] = run_samples,
) -> dict:
    """AC の提出について、基準（計算量が良くなる / 行数が半分以下）を満たす解き方だけを提案する。

    mistake_logs には保存しない。
    """
    warnings: list[str] = []
    data = generate(build_ac_prompt(problem, code), AC_SCHEMA)
    better_code = _strip_code_fence(data.get("better_code") or "").strip()
    correct_idea = (data.get("correct_idea") or "").strip()

    suggestion = None
    sample_cases: list = []
    note = ""
    if data.get("has_better") is True and better_code:
        label = judge_suggestion(
            code, better_code, data.get("faster") is True,
            data.get("current_complexity") or "", data.get("better_complexity") or "",
        )
        if label is None:
            note = "提案はありましたが、計算量が良くなる・行数が半分以下のどちらにも当てはまらないため出していません"
        else:
            check = runner(better_code, problem.samples)
            sample_cases = [asdict(c) for c in check.cases]
            if check.passed is False:
                note = "提案されたコードがサンプルを通らなかったため、提案はしません"
            else:
                if check.passed is None:
                    warnings.append("保存済みのサンプルがないため、提案コードは未確認です")
                diff, changed, total = compute_diff(code, better_code)
                suggestion = {
                    "improvement": label,
                    "code": better_code,
                    "reason": (data.get("suggestion_reason") or "").strip(),
                    "diff": diff,
                    "diff_lines": changed,
                    "total_lines": total,
                    "samples_passed": check.passed,
                }

    similar = find_similar(searcher, problem.problem_id, body_text, correct_idea, warnings) if correct_idea else []
    reference, next_problems = split_by_solved(db, similar, username)
    return {
        "suggestion": suggestion,
        "summary": "もっと良い解き方の提案があります" if suggestion else "この解き方で十分です",
        "current_complexity": (data.get("current_complexity") or "").strip(),
        "explanation": (data.get("current_review") or "").strip(),
        "note": note,
        "correct_idea": correct_idea,
        "sample_cases": sample_cases,
        "reference": [asdict(p) for p in reference],
        "next_problems": [asdict(p) for p in next_problems],
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 1 問の処理
# ---------------------------------------------------------------------------

def tutor_result_to_dict(result: TutorResult) -> dict:
    """家庭教師の結果を、API レスポンス・保存用の辞書にする。"""
    log = result.log
    return {
        "log_id": log.id,
        "created_at": log.created_at.isoformat() if log.created_at else None,
        "problem_id": log.problem_id,
        "verdict": log.verdict,
        "original_code": log.original_code,
        "fixed_code": log.fixed_code,
        "diff": log.diff,
        "diff_lines": log.diff_lines,
        "total_lines": result.total_lines,
        "mistake_level": log.mistake_level,
        "mistake_type": log.mistake_type,
        "samples_passed": log.samples_passed,
        "sample_cases": [asdict(c) for c in result.sample_cases],
        "attempts": result.attempts,
        "gap_summary": log.gap_summary,
        "correct_idea": log.correct_idea,
        "lesson": log.lesson,
        "past_same_type_count": result.past_same_type_count,
        "explanation": result.explanation,
        "reference": [asdict(p) for p in result.reference],
        "next_problems": [asdict(p) for p in result.next_problems],
        "warnings": result.warnings,
        "complexity": result.complexity,
        "estimated_ops": result.estimated_ops,
        "stress": asdict(result.stress) if result.stress is not None else None,
        "fix_status": log.fix_status,
        "submitted_verdict": log.submitted_verdict,
        "retry_of_id": log.retry_of_id,
    }


def update_report_after_submit(db: Session, log: MistakeLog, new_payload: dict | None) -> TutorReport | None:
    """修正版の提出結果を、その記録を表示している振り返りの行にも反映する。

    作り直した場合（new_payload あり）は、行の表示と記録をその新しい結果に差し替える。
    """
    report = db.scalar(select(TutorReport).where(TutorReport.mistake_log_id == log.id))
    if report is None:
        return None
    if new_payload is not None:
        report.payload = json.dumps(new_payload, ensure_ascii=False)
        report.mistake_log_id = new_payload["log_id"]
    else:
        payload = json.loads(report.payload or "{}")
        payload |= {"fix_status": log.fix_status, "submitted_verdict": log.submitted_verdict}
        report.payload = json.dumps(payload, ensure_ascii=False)
    db.commit()
    return report


@dataclass
class ReviewDeps:
    generate: Generate
    searcher: Searcher | None
    # 提出コードを手元で探す（見つからなければ None）。提出ページは robots.txt で禁止のため取得しない
    find_code: Callable[[TutorReport], str | None]
    # 問題文・サンプル・公式解説を用意する -> (問題データ, 公式解説が公開済みか)
    prepare_problem: Callable[[TutorReport], tuple[ProblemData, bool]]
    # 本問の公式解説本文（検索1 のクエリ。Gemini には渡さない）
    body_text: Callable[[str], str]
    generate_first: Generate | None = None
    runner: Callable[[str, list[dict]], SampleCheck] = run_samples
    stress_runner: StressRunner = run_stress


@dataclass
class _CallCounter:
    """Gemini の呼び出し回数を数える。"""

    count: int = 0

    def wrap(self, fn: Generate | None) -> Generate | None:
        if fn is None:
            return None

        def counted(prompt: str, schema: dict) -> dict:
            self.count += 1
            return fn(prompt, schema)

        return counted


def process_report(db: Session, report: TutorReport, deps: ReviewDeps) -> TutorReport:
    """pending の行を 1 問処理して done で保存する。done の行はそのまま返す（作り直さない）。

    失敗したときは error を記録して pending のまま保存し、例外を投げ直す。
    """
    if report.status == REPORT_DONE:
        return report

    counter = _CallCounter()
    try:
        if report.kind == KIND_SKIPPED:
            _, reason = classify_kind(report.verdict, report.language)
            _finish(db, report, {"reason": reason}, editorial_available=None, calls=0)
            return report

        if report.original_code is None:
            code = deps.find_code(report)
            if not code:
                raise CodeRequired(
                    f"{report.problem_id} の提出コードが手元のフォルダにありません。画面で貼り付けてください"
                )
            report.original_code = code
            db.commit()  # 再開時に取り直さないよう、コードは先に保存する

        problem, editorial_available = deps.prepare_problem(report)
        body_text = deps.body_text(report.problem_id) if editorial_available else ""
        generate = counter.wrap(deps.generate)

        if report.kind == KIND_MISTAKE:
            result = explain(
                db, generate, deps.searcher, problem, report.original_code, report.verdict,
                body_text=body_text, username=report.username, runner=deps.runner,
                generate_first=counter.wrap(deps.generate_first), stress_runner=deps.stress_runner,
            )
            payload = tutor_result_to_dict(result)
            report.mistake_log_id = result.log.id
        else:
            payload = review_accepted(
                db, generate, deps.searcher, problem, report.original_code, body_text,
                username=report.username, runner=deps.runner,
            )
        _finish(db, report, payload, editorial_available=editorial_available, calls=counter.count)
        return report
    except Exception as e:
        db.rollback()
        report.error = _error_text(e)
        report.gemini_calls += counter.count
        db.commit()
        raise


def _error_text(e: Exception) -> str:
    detail = getattr(e, "detail", None)
    return str(detail) if detail else f"{type(e).__name__}: {e}"


def _finish(db: Session, report: TutorReport, payload: dict, editorial_available: bool | None, calls: int) -> None:
    report.payload = json.dumps(payload, ensure_ascii=False)
    report.editorial_available = editorial_available
    report.gemini_calls += calls
    report.status = REPORT_DONE
    report.error = None
    db.commit()


# ---------------------------------------------------------------------------
# 外部アクセスの本物の実装
# ---------------------------------------------------------------------------

def set_report_code(db: Session, report: TutorReport, code: str) -> TutorReport:
    """画面で貼り付けた提出コードを保存する。処理済みの行は変えない。"""
    if report.status == REPORT_DONE:
        raise ReviewError("処理済みの問題のコードは変更できません")
    if not code.strip():
        raise ReviewError("コードが空です")
    report.original_code = code
    report.error = None
    db.commit()
    return report


def prepare_problem_data(
    client: AtCoderClient,
    report: TutorReport,
    index_editorials: Callable[[str], object] | None,
    base_dir: Path = EDITORIALS_DIR,
) -> tuple[ProblemData, bool]:
    """問題文・サンプル・公式解説を保存済みでなければ取得し、公式解説があれば解説ストアに登録する。"""
    meta = load_meta(report.problem_id, base_dir)
    if meta is None:
        fetch_and_save_problem(client, TargetProblem(
            problem_id=report.problem_id,
            contest_id=report.contest_id,
            problem_index=report.problem_index,
            title=report.title,
            difficulty=None,
            tags="",
        ), base_dir)
    elif not meta["editorials"]:
        # 前回取得したときは未公開だった解説が、公開されているかもしれない
        refresh_editorials(client, report.problem_id, base_dir)

    meta = load_meta(report.problem_id, base_dir)
    available = any(ed.get("editorial_type") == "official" for ed in meta["editorials"])
    if meta["editorials"] and index_editorials is not None:
        index_editorials(report.problem_id)

    problem = load_problem(report.problem_id, base_dir)
    if problem is None:
        raise ReviewError(f"{report.problem_id} の問題文を読み込めませんでした")
    return problem, available
