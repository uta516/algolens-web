from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ExplainRequest(BaseModel):
    # 解説ストアと同じ形式 e.g. "abc300_c"
    problem_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    code: str = Field(min_length=1, max_length=50_000)
    verdict: Literal["WA", "TLE", "RE"]
    # AC 済み判定に使う AtCoder ユーザー名（省略時は DB の全ユーザーの提出を見る）
    username: str | None = None


class SampleCaseOut(BaseModel):
    index: int
    status: str
    input: str
    expected: str
    actual: str
    stderr: str


class SimilarProblemOut(BaseModel):
    problem_id: str
    title: str
    difficulty: float | None
    reasons: list[str]
    url: str


class StressOut(BaseModel):
    status: str  # ok / TLE / skipped
    interpreter: str
    time_limit: float
    seconds: float | None
    input_bytes: int
    inputs: int = 0
    note: str


class EditOut(BaseModel):
    line: int
    action: str  # replace / delete / insert_after
    original: str
    new: str
    reason: str


class AttemptOut(BaseModel):
    attempt: int
    failed: str | None  # 落ちた確認（サンプル・愚直解との比較・計算回数・最大サイズ など）。通れば None
    detail: str


class BruteOut(BaseModel):
    status: str  # ok / mismatch / skipped
    total: int
    matched: int
    note: str
    failure: SampleCaseOut | None


class AlternativeOut(BaseModel):
    code: str
    complexity: str
    reason: str
    sample_cases: list[SampleCaseOut]
    stress: StressOut
    diff_lines: int
    total_lines: int


class ExplainResponse(BaseModel):
    log_id: int
    created_at: datetime
    problem_id: str
    verdict: str
    original_code: str
    fixed_code: str
    diff: str
    diff_lines: int
    total_lines: int
    mistake_level: str
    mistake_type: str
    samples_passed: bool | None
    sample_cases: list[SampleCaseOut]
    attempts: int
    gap_summary: str
    correct_idea: str
    lesson: str
    past_same_type_count: int
    explanation: str
    reference: list[SimilarProblemOut]
    next_problems: list[SimilarProblemOut]
    warnings: list[str]
    complexity: str
    estimated_ops: float | None
    stress: StressOut | None
    # 赤ペン（少ない修正）が全部の確認を通ったか。False なら「少ない修正では直せない」
    fix_found: bool
    edits: list[EditOut]
    attempt_log: list[AttemptOut]
    brute: BruteOut | None
    alternative: AlternativeOut | None
    fix_status: str | None
    submitted_verdict: str | None
    retry_of_id: int | None


class SubmitResultRequest(BaseModel):
    # 修正版を AtCoder に提出した判定
    verdict: Literal["AC", "WA", "TLE", "RE"]
    username: str | None = None


class SubmitResultResponse(BaseModel):
    log_id: int
    fix_status: str
    submitted_verdict: str
    # AC 以外のときに作り直した結果
    result: ExplainResponse | None
