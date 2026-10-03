"""振り返り: 最後の提出の選び方・WA 回数・AC と WA の振り分け・再開（作り直さない）のテスト。"""

import json

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.mistake_log import MistakeLog
from app.models.submission import Submission
from app.models.tutor_report import KIND_AC, KIND_MISTAKE, KIND_SKIPPED, REPORT_DONE, REPORT_PENDING, TutorReport
from app.services.review import (
    DB_NOT_SYNCED_WARNING,
    SYNC_FAILED_WARNING,
    ReviewDeps,
    ReviewError,
    gather_submissions,
    judge_suggestion,
    sync_user_submissions,
    plan_contest,
    problem_index_of,
    process_report,
    select_last_submissions,
)
from app.services.tutor import ProblemData

PY = "Python (CPython 3.11.4)"


def _sub(sid, problem, result, t, contest="abc400", language=PY):
    return {
        "id": sid, "epoch_second": t, "problem_id": problem, "contest_id": contest,
        "result": result, "language": language,
    }


# ---------------------------------------------------------------------------
# 最後の提出の選び方 / WA 回数
# ---------------------------------------------------------------------------

def test_select_last_submission_per_problem_by_time():
    subs = [
        _sub(3, "abc400_c", "AC", 300),
        _sub(1, "abc400_c", "WA", 100),
        _sub(2, "abc400_c", "TLE", 200),
        _sub(4, "abc400_a", "AC", 50),
    ]
    targets = select_last_submissions(subs, "abc400")
    assert [(t.problem_index, t.submission_id, t.verdict) for t in targets] == [
        ("A", 4, "AC"),
        ("C", 3, "AC"),
    ]


def test_select_last_submission_breaks_time_tie_by_id():
    subs = [_sub(11, "abc400_b", "WA", 100), _sub(12, "abc400_b", "AC", 100)]
    assert select_last_submissions(subs, "abc400")[0].submission_id == 12


def test_select_last_submission_ignores_other_contests():
    subs = [_sub(1, "abc400_a", "AC", 100), _sub(2, "abc399_a", "AC", 200, contest="abc399")]
    targets = select_last_submissions(subs, "abc400")
    assert [t.submission_id for t in targets] == [1]


def test_wa_count_counts_only_wa_tle_re_before_last():
    subs = [
        _sub(1, "abc400_d", "WA", 100),
        _sub(2, "abc400_d", "CE", 110),    # CE は数えない
        _sub(3, "abc400_d", "RE", 120),
        _sub(4, "abc400_d", "TLE", 130),
        _sub(5, "abc400_d", "WA", 140),    # 最後の提出自身は数えない
    ]
    target = select_last_submissions(subs, "abc400")[0]
    assert target.submission_id == 5
    assert target.verdict == "WA"
    assert target.wa_count == 3


def test_wa_count_zero_for_first_try():
    target = select_last_submissions([_sub(1, "abc400_a", "AC", 1)], "abc400")[0]
    assert target.wa_count == 0


def test_problem_index_of():
    assert problem_index_of("abc400_g") == "G"
    assert problem_index_of("abc001_1") == "A"


# ---------------------------------------------------------------------------
# DB と偽の外部アクセス
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_ORIGINAL = "a, b = map(int, input().split())\nprint(a * b)\n"
_RIGHT = _ORIGINAL.replace("*", "+")


def _ac_response(has_better=True, faster=False, better_code="", cur="O(1)", new=""):
    return {"current_complexity": cur, "has_better": has_better, "faster": faster,
            "better_complexity": new, "better_code": better_code, "current_review": "十分です",
            "suggestion_reason": "", "correct_idea": "足し算する"}


class _FakeLLM:
    """プロンプトの種類（修正案 / 最終解説 / AC の提案）を見て決まった JSON を返す。"""

    def __init__(self):
        self.prompts: list[str] = []

    def __call__(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        props = schema["properties"]
        if "explanation" in props and "has_better" not in props:
            return {"explanation": "解説"}
        if "has_better" in props:
            return _ac_response(has_better=False)
        return {"fixed_code": _RIGHT, "gap_summary": "掛け算していた", "mistake_type": "読み違い",
                "lesson": "演算子を確認する", "correct_idea": "足し算する"}


def _deps(llm, fetched: list | None = None, code: str | None = _ORIGINAL) -> ReviewDeps:
    def find_code(report):
        if fetched is not None:
            fetched.append(report.submission_id)
        return code

    def prepare_problem(report):
        return ProblemData(
            problem_id=report.problem_id, contest_id=report.contest_id, title=report.title,
            statement="A+B を出力せよ", samples=[{"input": "1 2\n", "output": "3\n"}],
        ), False

    return ReviewDeps(
        generate=llm, searcher=None, find_code=find_code,
        prepare_problem=prepare_problem, body_text=lambda pid: "",
    )


_SUBS = [
    _sub(1, "abc400_a", "AC", 100),
    _sub(2, "abc400_b", "WA", 200),
    _sub(3, "abc400_b", "WA", 300),
    _sub(4, "abc400_c", "CE", 400),
]
_TITLES = {"abc400_a": "A. Sum", "abc400_b": "B. Add", "abc400_c": "C. Hard"}


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------------------
# AC と WA の振り分け
# ---------------------------------------------------------------------------

def test_plan_assigns_kind_by_verdict_and_language(db):
    subs = _SUBS + [_sub(5, "abc400_d", "WA", 500, language="C++ 20 (gcc 12.2)")]
    reports = plan_contest(db, "me", "abc400", subs, _TITLES)

    kinds = {r.problem_index: r.kind for r in reports}
    assert kinds == {"A": KIND_AC, "B": KIND_MISTAKE, "C": KIND_SKIPPED, "D": KIND_SKIPPED}
    b = next(r for r in reports if r.problem_index == "B")
    assert (b.submission_id, b.wa_count, b.title) == (3, 1, "B. Add")
    assert all(r.status == REPORT_PENDING for r in reports)


def test_process_wa_goes_through_tutor_and_saves_mistake_log(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    wa = next(r for r in reports if r.kind == KIND_MISTAKE)
    llm = _FakeLLM()

    process_report(db, wa, _deps(llm))

    assert wa.status == REPORT_DONE
    assert wa.mistake_log_id is not None
    assert _count(db, MistakeLog) == 1
    payload = json.loads(wa.payload)
    assert payload["fixed_code"] == _RIGHT
    assert payload["mistake_level"] == "書き方"
    assert wa.gemini_calls == 2  # 修正案 + 最終解説


def test_process_ac_asks_for_better_solution_without_mistake_log(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    ac = next(r for r in reports if r.kind == KIND_AC)
    llm = _FakeLLM()

    process_report(db, ac, _deps(llm))

    assert ac.status == REPORT_DONE
    assert _count(db, MistakeLog) == 0
    assert ac.mistake_log_id is None
    payload = json.loads(ac.payload)
    assert payload["suggestion"] is None
    assert payload["summary"] == "この解き方で十分です"
    assert ac.gemini_calls == 1


def test_process_ac_shows_suggestion_only_when_samples_pass(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    ac = next(r for r in reports if r.kind == KIND_AC)

    def llm(prompt, schema):
        # 2 行 → 1 行（半分以下）
        return _ac_response(better_code="print(sum(map(int, input().split())))\n")

    process_report(db, ac, _deps(llm))

    suggestion = json.loads(ac.payload)["suggestion"]
    assert suggestion["improvement"].startswith("行数が半分以下")
    assert suggestion["samples_passed"] is True


def test_process_ac_drops_suggestion_that_fails_samples(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    ac = next(r for r in reports if r.kind == KIND_AC)

    def llm(prompt, schema):
        # 1 行（半分以下）だがサンプルを通らない
        return _ac_response(better_code="print(0)\n")

    process_report(db, ac, _deps(llm))

    payload = json.loads(ac.payload)
    assert payload["suggestion"] is None
    assert payload["summary"] == "この解き方で十分です"


def test_process_skipped_does_not_call_llm_or_fetch_code(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    ce = next(r for r in reports if r.kind == KIND_SKIPPED)
    llm, fetched = _FakeLLM(), []

    process_report(db, ce, _deps(llm, fetched))

    assert ce.status == REPORT_DONE
    assert "CE" in json.loads(ce.payload)["reason"]
    assert llm.prompts == [] and fetched == []


# ---------------------------------------------------------------------------
# 再開（作り直さない）
# ---------------------------------------------------------------------------

def test_plan_twice_does_not_duplicate_rows(db):
    plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    assert _count(db, TutorReport) == 3


def test_plan_keeps_done_rows_and_adds_newer_submission(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    for r in reports:
        process_report(db, r, _deps(_FakeLLM()))

    # B に新しい提出が増えた: B だけ新しい pending 行になり、他は done のまま
    reports = plan_contest(db, "me", "abc400", _SUBS + [_sub(9, "abc400_b", "AC", 900)], _TITLES)

    status = {r.problem_index: (r.submission_id, r.status) for r in reports}
    assert status == {"A": (1, REPORT_DONE), "B": (9, REPORT_PENDING), "C": (4, REPORT_DONE)}
    assert next(r for r in reports if r.problem_index == "B").wa_count == 2


def test_process_done_report_is_not_regenerated(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    wa = next(r for r in reports if r.kind == KIND_MISTAKE)
    process_report(db, wa, _deps(_FakeLLM()))
    payload_before = wa.payload

    llm, fetched = _FakeLLM(), []
    process_report(db, wa, _deps(llm, fetched))

    assert llm.prompts == [] and fetched == []
    assert wa.payload == payload_before
    assert _count(db, MistakeLog) == 1


def test_failed_report_stays_pending_and_resumes_without_refetching_code(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    wa = next(r for r in reports if r.kind == KIND_MISTAKE)

    def broken_llm(prompt, schema):
        raise RuntimeError("429 quota")

    fetched: list = []
    with pytest.raises(RuntimeError):
        process_report(db, wa, _deps(broken_llm, fetched))
    assert wa.status == REPORT_PENDING
    assert "429" in wa.error
    assert wa.original_code == _ORIGINAL  # 取得済みのコードは保存されている
    assert _count(db, MistakeLog) == 0     # 途中までの記録は残さない

    process_report(db, wa, _deps(_FakeLLM(), fetched))
    assert wa.status == REPORT_DONE
    assert wa.error is None
    assert fetched == [wa.submission_id]   # 提出コードは 1 回しか取りに行っていない


def test_missing_code_raises_and_stays_pending(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    ac = next(r for r in reports if r.kind == KIND_AC)
    with pytest.raises(ReviewError):
        process_report(db, ac, _deps(_FakeLLM(), code=None))
    assert ac.status == REPORT_PENDING


# ---------------------------------------------------------------------------
# AC の提案の基準（計算量が良くなる / 行数が半分以下）
# ---------------------------------------------------------------------------

def _lines(n: int, name: str = "x") -> str:
    return "".join(f"{name}{i} = {i}\n" for i in range(n))


def test_judge_suggestion_accepts_better_complexity():
    label = judge_suggestion(_lines(10), _lines(10), True, "O(N^2)", "O(N log N)")
    assert label == "計算量が良くなる（O(N^2) → O(N log N)）"


def test_judge_suggestion_rejects_faster_claim_with_same_complexity():
    # 定数倍の高速化だけなら提案しない（空白・大文字小文字の違いは同じとみなす）
    assert judge_suggestion(_lines(10), _lines(10), True, "O(N)", "o( n )") is None


def test_judge_suggestion_rejects_faster_claim_without_complexity():
    assert judge_suggestion(_lines(10), _lines(10), True, "O(N^2)", "") is None


def test_judge_suggestion_accepts_exactly_half_lines():
    assert judge_suggestion(_lines(10), _lines(5, "y"), False, "O(1)", "O(1)") == "行数が半分以下（10 行 → 5 行）"


def test_judge_suggestion_rejects_more_than_half_lines():
    assert judge_suggestion(_lines(10), _lines(6, "y"), False, "O(1)", "O(1)") is None


def test_judge_suggestion_ignores_blank_and_comment_lines():
    padded = "# コメント\n\n" + "\n".join(f"y{i} = {i}\n" for i in range(5)) + "    # おわり\n"
    assert judge_suggestion(_lines(10), padded, False, "", "") == "行数が半分以下（10 行 → 5 行）"


def test_process_ac_rejects_suggestion_that_misses_criteria(db):
    reports = plan_contest(db, "me", "abc400", _SUBS, _TITLES)
    ac = next(r for r in reports if r.kind == KIND_AC)

    def llm(prompt, schema):
        # 2 行 → 2 行で計算量も同じ: 基準を満たさない
        return _ac_response(better_code="x, y = map(int, input().split())\nprint(x + y)\n", new="O(1)")

    process_report(db, ac, _deps(llm))

    payload = json.loads(ac.payload)
    assert payload["suggestion"] is None
    assert payload["summary"] == "この解き方で十分です"
    assert payload["sample_cases"] == []  # 基準を満たさない提案はサンプル実行もしない
    assert "当てはまらない" in payload["note"]


# ---------------------------------------------------------------------------
# 提出データの同期に失敗したとき
# ---------------------------------------------------------------------------

_PROBLEMS = [{"id": p, "title": t} for p, t in _TITLES.items()]


def _api_down():
    raise httpx.ConnectError("[WinError 10054] 既存の接続はリモート ホストに強制的に切断されました。")


def test_gather_uses_db_submissions_when_api_fails(db):
    sync_user_submissions(db, "me", _SUBS, _PROBLEMS)  # 以前の同期で DB に入っている

    gathered = gather_submissions(db, "me", "abc400", _api_down, lambda: _PROBLEMS)

    assert gathered.warnings == [SYNC_FAILED_WARNING]
    assert gathered.synced == 0
    assert sorted(s["id"] for s in gathered.submissions) == [1, 2, 3, 4]
    # DB の提出からでも、最後の提出の選び方・WA 回数・振り分けが API のときと同じになる
    reports = plan_contest(db, "me", "abc400", gathered.submissions, _TITLES)
    summary = {r.problem_index: (r.submission_id, r.verdict, r.wa_count, r.kind) for r in reports}
    assert summary == {
        "A": (1, "AC", 0, KIND_AC),
        "B": (3, "WA", 1, KIND_MISTAKE),
        "C": (4, "CE", 0, KIND_SKIPPED),
    }


def test_gather_fails_when_api_fails_and_db_has_no_submissions_for_contest(db):
    # 別のコンテストの提出だけ DB にある
    sync_user_submissions(db, "me", [_sub(9, "abc399_a", "AC", 50, contest="abc399")], [{"id": "abc399_a", "title": "A"}])

    with pytest.raises(ReviewError, match="DB にも abc400 の提出がありません"):
        gather_submissions(db, "me", "abc400", _api_down, lambda: _PROBLEMS)


def test_gather_ignores_other_users_submissions_in_db(db):
    sync_user_submissions(db, "someone", _SUBS, _PROBLEMS)
    with pytest.raises(ReviewError):
        gather_submissions(db, "me", "abc400", _api_down, lambda: _PROBLEMS)


def test_gather_continues_without_sync_when_problem_list_fails(db):
    gathered = gather_submissions(db, "me", "abc400", lambda: _SUBS, _api_down)

    assert gathered.warnings == [DB_NOT_SYNCED_WARNING]
    assert gathered.submissions == _SUBS     # 取れた最新の提出で続ける
    assert _count(db, Submission) == 0       # DB には同期していない


def test_gather_syncs_without_warning_when_api_works(db):
    gathered = gather_submissions(db, "me", "abc400", lambda: _SUBS, lambda: _PROBLEMS)

    assert gathered.warnings == []
    assert gathered.synced == 4
    assert _count(db, Submission) == 4
