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
# やり直しと分岐の通し確認（LLM・検索は偽物）
# ---------------------------------------------------------------------------

from app.services.tutor import ProblemData, explain  # noqa: E402

_PROBLEM = ProblemData(
    problem_id="abc999_c",
    contest_id="abc999",
    title="C. Sum",
    statement="A+B を出力せよ",
    samples=[{"input": "1 2\n", "output": "3\n"}],
)
_ORIGINAL = "a, b = map(int, input().split())\nprint(a * b)\n"


class _FakeLLM:
    def __init__(self, fixes: list[str]):
        self.fixes = fixes
        self.prompts: list[str] = []

    def __call__(self, prompt: str, schema: dict) -> dict:
        self.prompts.append(prompt)
        if "explanation" in schema["properties"]:
            return {"explanation": "解説"}
        return {
            "fixed_code": self.fixes.pop(0),
            "gap_summary": "掛け算していた",
            "mistake_type": "読み違い",
            "lesson": "演算子を確認する",
            "correct_idea": "足し算する",
        }


def test_explain_retries_until_samples_pass_and_saves_log(db):
    wrong = _ORIGINAL.replace("*", "-")
    right = _ORIGINAL.replace("*", "+")
    llm = _FakeLLM([wrong, right])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="")

    assert result.attempts == 2
    assert "サンプル 1 が WA" in llm.prompts[1]  # 失敗内容を次の依頼に渡している
    assert result.log.samples_passed is True
    assert result.log.mistake_level == "書き方"
    assert result.log.diff_lines == 1
    assert db.get(MistakeLog, result.log.id).fixed_code == right


def test_explain_gives_up_after_max_retries_and_marks_thinking_mistake(db):
    wrong = _ORIGINAL.replace("*", "-")
    llm = _FakeLLM([wrong, wrong, wrong])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="")

    assert result.attempts == 3
    assert result.log.samples_passed is False
    assert result.log.mistake_level == "考え方"
    assert any("サンプルを通りませんでした" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# サンプルは通ったが変更が大きすぎるときのやり直し
# ---------------------------------------------------------------------------

from app.services.tutor import TOO_LARGE_FEEDBACK  # noqa: E402

_SMALL_RIGHT = _ORIGINAL.replace("*", "+")
# サンプルは通るが、元の 2 行に対して 5 行変わる書き直し
_LARGE_RIGHT = (
    "import sys\n"
    "def main():\n"
    "    x, y = map(int, sys.stdin.readline().split())\n"
    "    print(x + y)\n"
    "main()\n"
)
_LARGE_RIGHT_2 = _LARGE_RIGHT.replace("x, y", "p, q").replace("x + y", "p + q")


def _first_pass_prompts(llm: _FakeLLM) -> list[str]:
    return [p for p in llm.prompts if "explanation:" not in p]


def test_large_fix_is_retried_once_and_smaller_fix_is_adopted(db):
    llm = _FakeLLM([_LARGE_RIGHT, _SMALL_RIGHT])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="")

    prompts = _first_pass_prompts(llm)
    assert len(prompts) == 2
    assert TOO_LARGE_FEEDBACK in prompts[1]
    assert result.attempts == 2
    assert result.log.fixed_code == _SMALL_RIGHT
    assert result.log.diff_lines == 1
    assert result.log.mistake_level == "書き方"


def test_large_fix_stays_thinking_mistake_when_retry_is_still_large(db):
    llm = _FakeLLM([_LARGE_RIGHT, _LARGE_RIGHT_2])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="")

    assert len(_first_pass_prompts(llm)) == 2  # やり直しは 1 回だけ
    assert result.attempts == 2
    assert result.log.fixed_code == _LARGE_RIGHT
    assert result.log.samples_passed is True
    assert result.log.mistake_level == "考え方"


def test_large_fix_is_kept_when_retry_fails_samples(db):
    wrong = _ORIGINAL.replace("*", "-")
    llm = _FakeLLM([_LARGE_RIGHT, wrong])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="")

    assert result.log.fixed_code == _LARGE_RIGHT
    assert result.log.samples_passed is True
    assert result.log.mistake_level == "考え方"


def test_small_fix_is_not_retried(db):
    llm = _FakeLLM([_SMALL_RIGHT])

    result = explain(db, llm, None, _PROBLEM, _ORIGINAL, "WA", body_text="")

    assert len(_first_pass_prompts(llm)) == 1
    assert result.attempts == 1


def test_first_pass_uses_generate_first_when_given(db):
    first = _FakeLLM([_SMALL_RIGHT])
    other = _FakeLLM([])

    explain(db, other, None, _PROBLEM, _ORIGINAL, "WA", body_text="", generate_first=first)

    assert len(first.prompts) == 1
    assert len(other.prompts) == 1  # 最終解説だけ
    assert "explanation:" in other.prompts[0]
