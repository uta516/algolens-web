from pydantic import BaseModel, Field


class ContestOut(BaseModel):
    contest_id: str
    title: str
    start_epoch_second: int
    submission_count: int


class ImportRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    contest_id: str = Field(min_length=1, max_length=50, pattern=r"^abc[0-9]+$")


class ReportSummary(BaseModel):
    id: int
    contest_id: str
    problem_id: str
    problem_index: str
    title: str
    submission_id: int
    verdict: str
    language: str
    wa_count: int
    status: str
    kind: str
    editorial_available: bool | None
    gemini_calls: int
    error: str | None


class ReportOut(ReportSummary):
    original_code: str | None
    payload: dict | None


class SavedContestOut(BaseModel):
    contest_id: str
    problem_count: int
    done_count: int


class ImportResponse(BaseModel):
    # 今回 DB に追加した提出の件数
    synced_submissions: int
    reports: list[ReportSummary]
    # 提出データを最新にできなかったときなどの注意
    warnings: list[str] = []


class CodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=50_000)
