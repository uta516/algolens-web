"""振り返り: コンテストの最後の提出を問題ごとに取り込み、判定に応じて家庭教師の処理を行う。

流れ:
  plan_contest   提出一覧から問題ごとに最後の提出を選び、tutor_reports に pending で作る
                 （同じ提出の行が既にあれば作らない）
  process_report pending の行を 1 問ずつ処理して done にする（done の行は作り直さない）
                 - WA / TLE / RE: 家庭教師（tutor.explain）と同じ流れ
                 - AC: もっと簡単・速い解き方があるかを LLM に聞き、サンプルで確かめる
                 - それ以外（CE、Python 以外の言語など）: 対象外

1 問ごとにコミットするので、途中で止まっても pending の行から再開できる。
外部アクセス（AtCoder・Gemini・解説ストア）は ReviewDeps で差し替えられる。
"""

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tutor_report import (
    KIND_AC,
    KIND_MISTAKE,
    KIND_SKIPPED,
    REPORT_DONE,
    REPORT_PENDING,
    TutorReport,
)
from app.services.editorial_scraper import (
    ATCODER_BASE,
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
    SampleCheck,
    Searcher,
    TutorResult,
    compute_diff,
    explain,
    find_similar,
    load_problem,
    number_lines,
    run_samples,
    split_by_solved,
    _strip_code_fence,
)

MISTAKE_VERDICTS = ("WA", "TLE", "RE")


class ReviewError(Exception):
    """1 問の処理を続けられなかったときの例外（行は pending のまま残る）。"""


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
# AC の提案
# ---------------------------------------------------------------------------

AC_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "has_better": {"type": "BOOLEAN"},
        "improvement": {"type": "STRING", "enum": ["もっと簡単", "もっと速い", "なし"]},
        "better_code": {"type": "STRING"},
        "explanation": {"type": "STRING"},
        "correct_idea": {"type": "STRING"},
    },
    "required": ["has_better", "improvement", "better_code", "explanation", "correct_idea"],
}


def build_ac_prompt(problem: ProblemData, code: str) -> str:
    return f"""あなたは AtCoder の家庭教師です。生徒の Python 提出コードは AC しました。
もっと簡単な書き方（短く読みやすい）や、もっと速い解き方（計算量が良い）があるかを判断してください。

## 判断の基準
- 明らかに良くなる場合だけ has_better を true にする。書き方の好みの違い程度なら false
- false のときは improvement を "なし"、better_code を空文字にする
- true のときは better_code に標準入力から読み標準出力に書く Python コード全体を書く（コードブロック記号は付けない）

## 問題 ({problem.problem_id} {problem.title})
{problem.statement}

## 生徒のコード（各行の先頭は行番号）
```
{number_lines(code)}
```

## 出力（JSON）
- has_better: もっと簡単・速い解き方があるか
- improvement: "もっと簡単" / "もっと速い" / "なし"
- better_code: 提案するコード（なければ空文字）
- explanation: Markdown で簡潔に。今の解き方の評価と、提案があればどこが良くなるか（行番号を指して）
- correct_idea: この問題を解く考え方を一文で（使う手法名があれば手法名を含める）
"""


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
    """AC の提出について、もっと簡単・速い解き方を提案する。mistake_logs には保存しない。"""
    warnings: list[str] = []
    data = generate(build_ac_prompt(problem, code), AC_SCHEMA)
    better_code = _strip_code_fence(data.get("better_code") or "").strip()
    correct_idea = (data.get("correct_idea") or "").strip()

    suggestion = None
    sample_cases: list = []
    if data.get("has_better") is True and better_code:
        check = runner(better_code, problem.samples)
        sample_cases = [asdict(c) for c in check.cases]
        if check.passed is False:
            warnings.append("提案されたコードがサンプルを通らなかったため、提案はしません")
        else:
            if check.passed is None:
                warnings.append("保存済みのサンプルがないため、提案コードは未確認です")
            diff, changed, total = compute_diff(code, better_code)
            suggestion = {
                "improvement": data.get("improvement", ""),
                "code": better_code,
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
        "explanation": (data.get("explanation") or "").strip(),
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
    }


@dataclass
class ReviewDeps:
    generate: Generate
    searcher: Searcher | None
    # (contest_id, submission_id) -> 提出コード（取れなければ None）
    fetch_code: Callable[[str, int], str | None]
    # 問題文・サンプル・公式解説を用意する -> (問題データ, 公式解説が公開済みか)
    prepare_problem: Callable[[TutorReport], tuple[ProblemData, bool]]
    # 本問の公式解説本文（検索1 のクエリ。Gemini には渡さない）
    body_text: Callable[[str], str]
    generate_first: Generate | None = None
    runner: Callable[[str, list[dict]], SampleCheck] = run_samples


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
            code = deps.fetch_code(report.contest_id, report.submission_id)
            if not code:
                raise ReviewError("提出コードを取得できませんでした（提出ページが非公開の可能性があります）")
            report.original_code = code
            db.commit()  # 再開時に取り直さないよう、コードは先に保存する

        problem, editorial_available = deps.prepare_problem(report)
        body_text = deps.body_text(report.problem_id) if editorial_available else ""
        generate = counter.wrap(deps.generate)

        if report.kind == KIND_MISTAKE:
            result = explain(
                db, generate, deps.searcher, problem, report.original_code, report.verdict,
                body_text=body_text, username=report.username, runner=deps.runner,
                generate_first=counter.wrap(deps.generate_first),
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

def fetch_submission_code(client: AtCoderClient, contest_id: str, submission_id: int) -> str | None:
    """提出ページから提出コードを取り出す（auto_reporter.py と同じく #submission-code）。"""
    html = client.get(f"{ATCODER_BASE}/contests/{contest_id}/submissions/{submission_id}")
    pre = BeautifulSoup(html, "html.parser").select_one("pre#submission-code")
    return pre.get_text() if pre else None


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
