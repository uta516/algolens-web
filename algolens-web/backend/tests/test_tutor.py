"""家庭教師: 差分の計算・書き方/考え方の分岐・サンプル実行・mistake_logs の保存のテスト。"""

import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.mistake_log import MistakeLog
from app.services.tutor import (
    SampleCheck,
    classify_level,
    compute_diff,
    count_past_same_type,
    outputs_match,
    run_samples,
    save_mistake_log,
)


# ---------------------------------------------------------------------------
# 差分の計算
# ---------------------------------------------------------------------------

def test_compute_diff_identical_code_has_no_changes():
    code = "n = int(input())\nprint(n)\n"
    diff, changed, total = compute_diff(code, code)
    assert changed == 0
    assert total == 2
    assert diff == ""


def test_compute_diff_counts_replaced_line_once():
    original = "n = int(input())\nprint(n + 1)\n"
    fixed = "n = int(input())\nprint(n)\n"
    diff, changed, total = compute_diff(original, fixed)
    assert changed == 1
    assert total == 2
    assert "-print(n + 1)" in diff
    assert "+print(n)" in diff


def test_compute_diff_counts_inserted_and_deleted_lines():
    original = "a\nb\nc\n"
    fixed = "a\nx\ny\nc\nd\n"  # b → x,y（置換で 2 行）と d の追加（1 行）
    _, changed, total = compute_diff(original, fixed)
    assert changed == 3
    assert total == 3


def test_compute_diff_ignores_trailing_whitespace_and_crlf():
    original = "a = 1   \r\nprint(a)\r\n"
    fixed = "a = 1\nprint(a)\n"
    _, changed, _ = compute_diff(original, fixed)
    assert changed == 0


# ---------------------------------------------------------------------------
# 書き方 / 考え方 の分岐
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("changed", "total", "samples_passed", "expected"),
    [
        (0, 10, True, "書き方"),
        (3, 5, True, "書き方"),       # 60% でも 3 行以下なら書き方
        (4, 20, True, "書き方"),      # ちょうど 20%
        (5, 20, True, "考え方"),      # 25% かつ 4 行超
        (10, 30, None, "考え方"),     # サンプルなしでも差分の大きさで判定
        (2, 30, None, "書き方"),
        (1, 100, False, "考え方"),    # サンプルを通らなければ差分が小さくても考え方
    ],
)
def test_classify_level(changed, total, samples_passed, expected):
    assert classify_level(changed, total, samples_passed) == expected


def test_classify_level_empty_original_code():
    assert classify_level(4, 0, True) == "考え方"


# ---------------------------------------------------------------------------
# サンプル実行
# ---------------------------------------------------------------------------

def test_outputs_match_ignores_whitespace_differences():
    assert outputs_match("1 2\n3\n", "1  2 3")
    assert not outputs_match("1 2\n", "1 3\n")
    assert not outputs_match("1 2\n", "1 2 3\n")


def test_outputs_match_allows_small_float_error():
    assert outputs_match("0.333333333\n", "0.3333333333333\n")
    assert not outputs_match("0.33\n", "0.34\n")


def test_run_samples_without_samples_returns_none():
    check = run_samples("print(1)", [])
    assert check.passed is None
    assert check.cases == []


def test_run_samples_all_pass():
    code = "a, b = map(int, input().split())\nprint(a + b)\n"
    samples = [
        {"input": "1 2\n", "output": "3\n"},
        {"input": "10 20\n", "output": "30\n"},
    ]
    check = run_samples(code, samples)
    assert check.passed is True
    assert [c.status for c in check.cases] == ["AC", "AC"]


def test_run_samples_detects_wrong_answer():
    code = "a, b = map(int, input().split())\nprint(a * b)\n"
    samples = [{"input": "1 2\n", "output": "3\n"}]
    check = run_samples(code, samples)
    assert check.passed is False
    assert check.cases[0].status == "WA"
    assert check.cases[0].actual.strip() == "2"
    assert check.first_failure() is check.cases[0]


def test_run_samples_detects_runtime_error():
    code = "raise ValueError('boom')\n"
    check = run_samples(code, [{"input": "\n", "output": "1\n"}])
    assert check.passed is False
    assert check.cases[0].status == "RE"
    assert "ValueError" in check.cases[0].stderr


def test_run_samples_detects_time_limit():
    code = "while True:\n    pass\n"
    check = run_samples(code, [{"input": "\n", "output": "1\n"}], time_limit=0.5)
    assert check.passed is False
    assert check.cases[0].status == "TLE"


def test_run_samples_handles_japanese_output():
    code = "print('はい')\n"
    check = run_samples(code, [{"input": "\n", "output": "はい\n"}])
    assert check.passed is True


def test_run_samples_uses_current_interpreter():
    code = "import sys\nprint(sys.version_info[0])\n"
    check = run_samples(code, [{"input": "", "output": f"{sys.version_info[0]}\n"}])
    assert check.passed is True


# ---------------------------------------------------------------------------
# mistake_logs の保存と集計
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


def _log_kwargs(**overrides):
    base = dict(
        problem_id="abc300_c",
        original_code="print(1)\n",
        fixed_code="print(2)\n",
        diff="-print(1)\n+print(2)\n",
        verdict="WA",
        diff_lines=1,
        mistake_level="書き方",
        mistake_type="境界・インデックス",
        samples_passed=True,
        gap_summary="出力する値を 1 ずらしていた",
        correct_idea="0 始まりで数える",
        lesson="添字の始まりを確認する",
    )
    base.update(overrides)
    return base


def test_save_mistake_log_persists_all_fields(db):
    log = save_mistake_log(db, **_log_kwargs())
    assert log.id is not None
    assert log.created_at is not None

    stored = db.get(MistakeLog, log.id)
    assert stored.problem_id == "abc300_c"
    assert stored.verdict == "WA"
    assert stored.diff_lines == 1
    assert stored.mistake_level == "書き方"
    assert stored.mistake_type == "境界・インデックス"
    assert stored.samples_passed is True
    assert stored.lesson == "添字の始まりを確認する"


def test_save_mistake_log_keeps_null_samples_passed(db):
    log = save_mistake_log(db, **_log_kwargs(samples_passed=None))
    assert db.get(MistakeLog, log.id).samples_passed is None


def test_save_mistake_log_rejects_unknown_type_and_level(db):
    with pytest.raises(ValueError):
        save_mistake_log(db, **_log_kwargs(mistake_type="うっかり"))
    with pytest.raises(ValueError):
        save_mistake_log(db, **_log_kwargs(mistake_level="その他"))


def test_count_past_same_type_excludes_current_log(db):
    save_mistake_log(db, **_log_kwargs(problem_id="abc001_c"))
    save_mistake_log(db, **_log_kwargs(problem_id="abc002_c", mistake_type="考察不足"))
    current = save_mistake_log(db, **_log_kwargs(problem_id="abc003_c"))

    assert count_past_same_type(db, "境界・インデックス", exclude_id=current.id) == 1
    assert count_past_same_type(db, "考察不足", exclude_id=current.id) == 1
    assert count_past_same_type(db, "読み違い", exclude_id=current.id) == 0


def test_sample_check_first_failure_none_when_passed():
    assert SampleCheck(passed=True, cases=[]).first_failure() is None


# ---------------------------------------------------------------------------
# やり直しと分岐の通し確認（LLM・検索・確認の実行は偽物）
# ---------------------------------------------------------------------------

from app.models.mistake_log import FIX_CONFIRMED, FIX_FAILED  # noqa: E402
from app.services.checkers import (  # noqa: E402
    BRUTE_OK,
    BruteCases,
    MemoryCheckerStore,
    ProblemCheckers,
    compare_with_brute,
    prepare_brute_cases,
)
from app.services.redpen import EditError, apply_edits, parse_edits  # noqa: E402
from app.services.tutor import (  # noqa: E402
    CHECK_BRUTE,
    CHECK_EDITS,
    CHECK_OPS,
    CHECK_SAMPLES,
    CHECK_STRESS,
    OPS_LIMIT,
    STRESS_OK,
    STRESS_SKIPPED,
    STRESS_TLE,
    STRESS_TLE_FEEDBACK,
    Checks,
    ProblemData,
    StressCheck,
    TutorError,
    explain,
    record_submit_result,
    run_stress,
)

_PROBLEM = ProblemData(
    problem_id="abc999_c",
    contest_id="abc999",
    title="C. Sum",
    statement="A+B を出力せよ",
    samples=[{"input": "1 2\n", "output": "3\n"}],
)
_ORIGINAL = "a, b = map(int, input().split())\nprint(a * b)\n"
_GEN = "print('1 2')\n"
_RIGHT_LINE = "print(a + b)"
_SLOW_LINE = "print(sum([a, b]))"   # 正しいが、最大サイズの入力で時間切れになる想定
_WRONG_LINE = "print(a - b)"


def _fixed(line: str) -> str:
    return f"a, b = map(int, input().split())\n{line}\n"


def _edit(line_text: str, ops: float = 1e6, **extra) -> dict:
    """2 行目を line_text に置き換える赤ペンの応答。"""
    return {
        "edits": [{"line": 2, "action": "replace", "original": "print(a * b)", "new": line_text, "reason": "直す"}],
        "estimated_ops": ops,
    } | extra


class _FakeLLM:
    """1 回目の応答を順に返す偽物（分析項目は共通）。最終解説には決まった文を返す。"""

    def __init__(self, responses: list[dict], mistake_type: str = "読み違い"):
        self.responses = responses
        self.mistake_type = mistake_type
        self.prompts: list[str] = []
        self.schemas: list[dict] = []

    def __call__(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        self.schemas.append(schema)
        if "explanation" in schema["properties"]:
            return {"explanation": "解説"}
        return {
            "gap_summary": "掛け算していた",
            "mistake_type": self.mistake_type,
            "lesson": "演算子を確認する",
            "correct_idea": "足し算する",
            "complexity": "O(1)",
        } | self.responses.pop(0)


def _first_pass_prompts(llm: _FakeLLM) -> list[str]:
    return [p for p in llm.prompts if "explanation:" not in p]


class _FakeStress:
    """修正コードごとに決めた結果を返す（指定がなければ 0.1 秒で通る）。"""

    def __init__(self, tle_codes=frozenset()):
        self.tle_codes = set(tle_codes)
        self.calls: list[str] = []

    def __call__(self, code: str, generators: list[str], time_limit: float) -> StressCheck:
        self.calls.append(code)
        if code in self.tle_codes:
            return StressCheck(STRESS_TLE, "CPython", time_limit * 5)
        return StressCheck(STRESS_OK, "CPython", time_limit * 5, seconds=0.1, input_bytes=10, inputs=1)


def _checks(stress=None, brute: bool = False, **kwargs) -> Checks:
    """最大サイズの入力を作るコード（と、brute なら愚直解）を保存済みにした確認。"""
    store = MemoryCheckerStore()
    checkers = ProblemCheckers(max_generators=[_GEN])
    if brute:
        checkers.brute_code = "a, b = map(int, input().split())\nprint(a + b)\n"
        checkers.small_generator = "print('2 5')\n"
    store.save(_PROBLEM.problem_id, checkers)
    defaults = dict(
        stress=stress or _FakeStress(),
        prepare_brute=lambda b, s: BruteCases([("2 5\n", "7\n")]),
        store=store,
    )
    return Checks(**(defaults | kwargs))


def test_explain_retries_until_samples_pass_and_saves_log(db):
    llm = _FakeLLM([_edit(_WRONG_LINE), _edit(_RIGHT_LINE)])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks())

    assert result.attempts == 2
    assert "サンプル 1 が WA" in llm.prompts[1]  # 失敗内容を次の依頼に渡している
    assert "前回の赤ペン" in llm.prompts[1]
    assert result.fix_found is True
    assert result.log.samples_passed is True
    assert result.log.mistake_level == "書き方"
    assert result.log.diff_lines == 1
    assert db.get(MistakeLog, result.log.id).fixed_code == _fixed(_RIGHT_LINE)
    assert [a.failed for a in result.attempt_log] == [CHECK_SAMPLES, None]


def test_fix_not_found_after_max_retries_is_thinking_mistake(db):
    llm = _FakeLLM([_edit(_WRONG_LINE)] * 3)

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks())

    assert result.attempts == 3
    assert result.fix_found is False
    assert result.log.fix_found is False
    assert result.log.mistake_level == "考え方"
    assert "少ない修正（赤ペン）では確認を通せませんでした" in llm.prompts[-1]
    with pytest.raises(TutorError):  # 提出する修正版がないので、提出結果は戻せない
        record_submit_result(db, result.log, "WA")


def test_first_pass_uses_generate_first_when_given(db):
    first = _FakeLLM([_edit(_RIGHT_LINE)])
    other = _FakeLLM([])

    explain(db, other, None, _PROBLEM, _ORIGINAL, "WA", body_text="", generate_first=first, checks=_checks())

    assert len(first.prompts) == 1
    assert len(other.prompts) == 1  # 最終解説だけ
    assert "explanation:" in other.prompts[0]


# ---------------------------------------------------------------------------
# 赤ペン（変更の一覧）とコメント・空行
# ---------------------------------------------------------------------------

_COMMENTED = "# テンプレート\n#   N = int(input())\n\na, b = map(int, input().split())\n\nprint(a * b)  # 出力\n"


def test_apply_edits_keeps_comments_and_blank_lines():
    edits = parse_edits([
        {"line": 6, "action": "replace", "original": "print(a * b)  # 出力", "new": "print(a + b)  # 出力", "reason": ""},
        {"line": 0, "action": "insert_after", "original": "", "new": "import sys", "reason": ""},
        {"line": 4, "action": "insert_after", "original": "", "new": "c = 0\nd = 0", "reason": ""},
    ])
    fixed = apply_edits(_COMMENTED, edits)
    assert fixed == (
        "import sys\n# テンプレート\n#   N = int(input())\n\na, b = map(int, input().split())\nc = 0\nd = 0\n\n"
        "print(a + b)  # 出力\n"
    )


def test_apply_edits_rejects_wrong_original_and_delete():
    with pytest.raises(EditError, match="合いません"):
        apply_edits(_ORIGINAL, parse_edits([{"line": 1, "action": "replace", "original": "print(a * b)", "new": "x", "reason": ""}]))
    edits = parse_edits([{"line": 2, "action": "delete", "original": "print(a * b)", "new": "", "reason": ""}])
    assert apply_edits(_ORIGINAL, edits) == "a, b = map(int, input().split())\n"


def test_compute_diff_ignores_comment_and_blank_lines():
    fixed = "a, b = map(int, input().split())\nprint(a + b)\n"
    _, changed, total = compute_diff(_COMMENTED, fixed)  # コメント・空行の削除は数えない
    assert total == 2
    assert changed == 1


def test_edits_that_do_not_match_code_are_retried(db):
    bad = {"edits": [{"line": 1, "action": "replace", "original": "print(a * b)", "new": _RIGHT_LINE, "reason": ""}],
           "estimated_ops": 1}
    llm = _FakeLLM([bad, _edit(_RIGHT_LINE)])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks())

    assert [a.failed for a in result.attempt_log] == [CHECK_EDITS, None]
    assert "original が元のコードと合いません" in _first_pass_prompts(llm)[1]
    assert result.log.fixed_code == _fixed(_RIGHT_LINE)


def test_comment_lines_in_original_are_kept_in_fixed_code(db):
    edit = {"edits": [{"line": 6, "action": "replace", "original": "print(a * b)  # 出力",
                       "new": "print(a + b)  # 出力", "reason": ""}], "estimated_ops": 1}
    llm = _FakeLLM([edit])

    result = explain(db, llm, None, _PROBLEM, _COMMENTED, "WA", body_text="", checks=_checks())

    assert result.log.fixed_code.startswith("# テンプレート\n#   N = int(input())\n\n")
    assert result.log.diff_lines == 1
    assert result.total_lines == 2


# ---------------------------------------------------------------------------
# 愚直解との比較
# ---------------------------------------------------------------------------

def test_brute_mismatch_is_retried_and_logged(db):
    # サンプル (1 2 → 3) は通るが、小さい入力 (2 5 → 7) で答えが違う
    llm = _FakeLLM([_edit("print(3)"), _edit(_RIGHT_LINE)])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks(brute=True))

    assert [a.failed for a in result.attempt_log] == [CHECK_BRUTE, None]
    assert "愚直解" in _first_pass_prompts(llm)[1] and "2 5" in _first_pass_prompts(llm)[1]
    assert result.brute.status == BRUTE_OK
    assert result.log.fixed_code == _fixed(_RIGHT_LINE)


def test_prepare_and_compare_with_brute_runs_real_code():
    brute = "a, b = map(int, input().split())\nprint(a + b)\n"
    gen = "import random, sys\nrandom.seed(int(sys.argv[1]))\nprint(random.randint(1, 9), random.randint(1, 9))\n"
    cases = prepare_brute_cases(brute, gen, n=3)
    assert cases.note == "" and len(cases.cases) == 3
    assert compare_with_brute(brute, cases).status == BRUTE_OK
    check = compare_with_brute("print(0)\n", cases)
    assert check.status == "mismatch" and check.failure.status == "WA"


def test_checkers_are_saved_and_not_requested_again(db):
    store = MemoryCheckerStore()
    checks = Checks(stress=_FakeStress(), check_generator=lambda g: "", store=store,
                    prepare_brute=lambda b, s: BruteCases([("2 5\n", "7\n")]))
    brute = {"brute_code": "a, b = map(int, input().split())\nprint(a + b)\n",
             "small_input_generator": "print('2 5')\n", "max_input_generators": [_GEN]}
    first = _FakeLLM([_edit(_RIGHT_LINE, **brute)])

    explain(db, first, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=checks)

    assert "brute_code" in first.schemas[0]["properties"]
    saved = store.load(_PROBLEM.problem_id)
    assert saved.has_brute and saved.max_generators == [_GEN]

    second = _FakeLLM([_edit(_RIGHT_LINE)])
    result = explain(db, second, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=checks)

    props = second.schemas[0]["properties"]
    assert "brute_code" not in props and "max_input_generators" not in props
    assert result.brute.status == BRUTE_OK


def test_brute_that_fails_samples_is_not_saved(db):
    store = MemoryCheckerStore()
    checks = Checks(stress=_FakeStress(), check_generator=lambda g: "", store=store)
    llm = _FakeLLM([_edit(_RIGHT_LINE, brute_code="print(0)\n", small_input_generator="print('2 5')\n",
                          max_input_generators=[_GEN])])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=checks)

    assert not store.load(_PROBLEM.problem_id).has_brute
    assert result.brute is None
    assert any("愚直解がサンプルを通らなかった" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# 別解
# ---------------------------------------------------------------------------

def test_alternative_is_shown_only_when_checks_pass(db):
    alt = "print(sum(map(int, input().split())))\n"
    llm = _FakeLLM([_edit(_RIGHT_LINE, alternative_code=alt, alternative_complexity="O(1)",
                          alternative_reason="1 行で書ける")])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks())

    assert result.alternative is not None and result.alternative.code == alt
    assert result.log.fixed_code == _fixed(_RIGHT_LINE)  # 別解は赤ペンの代わりにしない


def test_alternative_that_fails_is_hidden(db):
    slow_alt = "print(sum(map(int, input().split())))  # slow\n"
    llm = _FakeLLM([_edit(_RIGHT_LINE, alternative_code=slow_alt)])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="",
                     checks=_checks(stress=_FakeStress(tle_codes={slow_alt})))

    assert result.alternative is None
    assert any("別解はありましたが" in w for w in result.warnings)


def test_alternative_is_asked_only_in_first_call(db):
    llm = _FakeLLM([_edit(_WRONG_LINE), _edit(_RIGHT_LINE)])

    explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks())

    assert "alternative_code" in llm.schemas[0]["properties"]
    assert "alternative_code" not in llm.schemas[1]["properties"]


# ---------------------------------------------------------------------------
# 最大サイズの入力での時間切れ・計算回数の目安によるやり直し
# ---------------------------------------------------------------------------

def test_stress_tle_asks_to_improve_complexity_and_retries(db):
    llm = _FakeLLM([_edit(_SLOW_LINE), _edit(_RIGHT_LINE)])
    stress = _FakeStress(tle_codes={_fixed(_SLOW_LINE)})

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "TLE", body_text="", checks=_checks(stress))

    prompts = _first_pass_prompts(llm)
    assert len(prompts) == 2
    assert STRESS_TLE_FEEDBACK in prompts[1]
    assert [a.failed for a in result.attempt_log] == [CHECK_STRESS, None]
    assert result.log.fixed_code == _fixed(_RIGHT_LINE)
    assert result.stress.status == STRESS_OK
    assert stress.calls == [_fixed(_SLOW_LINE), _fixed(_RIGHT_LINE)]


def test_stress_tle_retries_count_toward_the_retry_limit(db):
    llm = _FakeLLM([_edit(_SLOW_LINE)] * 3)
    stress = _FakeStress(tle_codes={_fixed(_SLOW_LINE)})

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "TLE", body_text="", checks=_checks(stress))

    assert len(_first_pass_prompts(llm)) == 3  # 1 回目 + やり直し 2 回で打ち切り
    assert result.stress.status == STRESS_TLE
    assert result.fix_found is False
    assert [a.failed for a in result.attempt_log] == [CHECK_STRESS] * 3


def test_skipped_stress_check_is_warned_and_not_retried(db):
    def broken(code, generators, time_limit):
        return StressCheck(STRESS_SKIPPED, "CPython", 10.0, note="入力を作るコードの出力が空でした")

    llm = _FakeLLM([_edit(_RIGHT_LINE)])
    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks(broken))

    assert len(_first_pass_prompts(llm)) == 1
    assert result.fix_found is True
    assert any("最大サイズの入力での確認を飛ばしました" in w for w in result.warnings)


def test_run_stress_detects_time_limit_exceeded():
    check = run_stress("while True:\n    pass\n", [_GEN], problem_time_limit=0.1)
    assert check.status == STRESS_TLE


def test_run_stress_skips_when_generator_fails():
    check = run_stress(_fixed(_RIGHT_LINE), ["raise SystemExit(1)\n"], problem_time_limit=0.5)
    assert check.status == STRESS_SKIPPED


def test_run_stress_uses_every_generator_and_skips_broken_ones():
    check = run_stress(_fixed(_RIGHT_LINE), [_GEN, "raise SystemExit(1)\n", "print('3 4')\n"], problem_time_limit=0.5)
    assert check.status == STRESS_OK
    assert check.inputs == 2
    assert "入力 2" in check.note


def test_too_many_estimated_ops_is_rebuilt_without_running(db):
    llm = _FakeLLM([_edit(_SLOW_LINE, ops=OPS_LIMIT * 20), _edit(_RIGHT_LINE)])
    stress = _FakeStress()
    ran: list[str] = []

    def runner(code, samples):
        ran.append(code)
        return run_samples(code, samples)

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "TLE", body_text="", checks=_checks(stress, runner=runner))

    prompts = _first_pass_prompts(llm)
    assert len(prompts) == 2
    assert "計算回数の目安" in prompts[1] and "10^8" in prompts[1]
    assert ran == [_fixed(_RIGHT_LINE)]     # 目安が多すぎる案は実行していない
    assert stress.calls == [_fixed(_RIGHT_LINE)]
    assert [a.failed for a in result.attempt_log] == [CHECK_OPS, None]


def test_estimated_ops_within_limit_is_run(db):
    llm = _FakeLLM([_edit(_RIGHT_LINE, ops=OPS_LIMIT)])
    stress = _FakeStress()

    explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks(stress))

    assert len(_first_pass_prompts(llm)) == 1
    assert stress.calls == [_fixed(_RIGHT_LINE)]


# ---------------------------------------------------------------------------
# 修正版を提出した結果を戻したときの記録の扱い
# ---------------------------------------------------------------------------

def test_submit_ac_marks_log_confirmed(db):
    log = save_mistake_log(db, **_log_kwargs())

    record_submit_result(db, log, "AC")

    stored = db.get(MistakeLog, log.id)
    assert stored.fix_status == FIX_CONFIRMED
    assert stored.submitted_verdict == "AC"
    assert count_past_same_type(db, "境界・インデックス") == 1  # 確認済みは数える
    with pytest.raises(TutorError):
        record_submit_result(db, log, "WA")


def test_submit_failure_marks_log_failed_and_excludes_it_from_count(db):
    save_mistake_log(db, **_log_kwargs(problem_id="abc001_c"))
    log = save_mistake_log(db, **_log_kwargs(problem_id="abc002_c"))
    assert count_past_same_type(db, "境界・インデックス") == 2

    record_submit_result(db, log, "TLE")

    assert db.get(MistakeLog, log.id).fix_status == FIX_FAILED
    assert db.get(MistakeLog, log.id).submitted_verdict == "TLE"
    assert count_past_same_type(db, "境界・インデックス") == 1


def test_submit_failure_rebuilds_fix_with_the_result(db):
    first = explain(db, _FakeLLM([_edit(_SLOW_LINE)], mistake_type="計算量の見積もりミス"),
                    None, _PROBLEM, _ORIGINAL, "TLE", body_text="", checks=_checks())
    record_submit_result(db, first.log, "TLE")

    llm = _FakeLLM([_edit(_RIGHT_LINE)], mistake_type="計算量の見積もりミス")
    second = explain(db, llm, None, _PROBLEM, _ORIGINAL, "TLE", body_text="",
                     checks=_checks(), retry_of=first.log)

    prompt = _first_pass_prompts(llm)[0]
    assert "前回の修正版を AtCoder に提出したところ TLE" in prompt
    assert _SLOW_LINE in prompt                          # 前回の修正版を見せている
    assert second.log.retry_of_id == first.log.id
    assert second.log.fix_status is None                # 新しい修正版は提出での確認はまだ
    assert second.past_same_type_count == 0             # 修正失敗の記録は数えない
    assert db.get(MistakeLog, first.log.id).fix_status == FIX_FAILED
    with pytest.raises(TutorError):                     # 作り直し済みなら記録し直せない
        record_submit_result(db, first.log, "TLE")


def test_submit_failure_can_retry_rebuild_when_previous_rebuild_failed(db):
    log = save_mistake_log(db, **_log_kwargs())
    record_submit_result(db, log, "WA")

    # 作り直しが失敗して新しい記録がなければ、同じ結果でもう一度選べる（違う結果は不可）
    assert record_submit_result(db, log, "WA").fix_status == FIX_FAILED
    with pytest.raises(TutorError):
        record_submit_result(db, log, "TLE")


# ---------------------------------------------------------------------------
# 赤ペンが書き直しになったとき
# ---------------------------------------------------------------------------

from app.services.tutor import CHECK_SIZE, is_rewrite  # noqa: E402

# 元のコード 8 行（コメント・空行を除く）。2 行目だけ直せば正しい
_LONG = "a, b = map(int, input().split())\nprint(a * b)\n" + "".join(f"x{i} = {i}\n" for i in range(6))


def _rewrite_edits(n: int) -> dict:
    """2 行目を直し、さらに 3 行目以降の n 行を書き換える赤ペン。"""
    edits = [{"line": 2, "action": "replace", "original": "print(a * b)", "new": _RIGHT_LINE, "reason": ""}]
    edits += [{"line": 3 + i, "action": "replace", "original": f"x{i} = {i}", "new": f"y{i} = {i}", "reason": ""}
              for i in range(n)]
    return {"edits": edits, "estimated_ops": 1}


def test_compute_diff_counts_lines_written_not_lines_removed():
    original = "if c:\n    if d:\n        print(1)\n    else:\n        print(2)\n"
    fixed = "if c:\n    print(1)\n"  # 入れ子をほどいて 1 行にまとめた
    _, changed, total = compute_diff(original, fixed)
    assert (changed, total) == (1, 5)


def test_is_rewrite_when_more_than_half_of_lines_change():
    assert not is_rewrite(3, 4)       # 3 行以下は小さい直し
    assert not is_rewrite(4, 8)       # ちょうど半分
    assert is_rewrite(5, 8)


def test_rewrite_is_sent_back_and_smaller_fix_is_adopted(db):
    llm = _FakeLLM([_rewrite_edits(4), _rewrite_edits(0)])

    result = explain(db, llm, None, _PROBLEM, _LONG, "WA", body_text="", checks=_checks())

    assert [a.failed for a in result.attempt_log] == [CHECK_SIZE, None]
    assert "変更が大きすぎます" in _first_pass_prompts(llm)[1]
    assert result.log.diff_lines == 1


def test_rewrite_until_limit_means_fix_not_found(db):
    llm = _FakeLLM([_rewrite_edits(4)] * 3)

    result = explain(db, llm, None, _PROBLEM, _LONG, "WA", body_text="", checks=_checks())

    assert result.fix_found is False
    assert result.log.mistake_level == "考え方"
    assert result.sample_cases  # 実行前に止まっても、表示用にサンプルの結果は取る


def test_edits_on_blank_or_comment_lines_are_rejected():
    with pytest.raises(EditError, match="空行かコメント"):
        apply_edits(_COMMENTED, parse_edits([{"line": 3, "action": "replace", "original": "", "new": "x = 1", "reason": ""}]))
    with pytest.raises(EditError, match="空行かコメント"):
        apply_edits(_COMMENTED, parse_edits([{"line": 1, "action": "delete", "original": "# テンプレート", "new": "", "reason": ""}]))


def test_no_op_replace_is_ignored():
    edits = parse_edits([{"line": 1, "action": "replace", "original": "a, b = map(int, input().split())",
                          "new": "a, b = map(int, input().split())", "reason": ""}])
    assert apply_edits(_ORIGINAL, edits) == _ORIGINAL


def test_counterexample_for_original_code_is_shown_to_llm(db):
    # 元のコード（掛け算）は保存済みの愚直解の入力 2 5 で 10 を出し、正しい答え 7 と違う
    llm = _FakeLLM([_edit(_RIGHT_LINE)])

    explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="", checks=_checks(brute=True))

    prompt = _first_pass_prompts(llm)[0]
    assert "私のコードが間違える小さい入力" in prompt
    assert "2 5" in prompt and "10" in prompt
