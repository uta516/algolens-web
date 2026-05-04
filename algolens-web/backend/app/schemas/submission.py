from datetime import datetime

from pydantic import BaseModel


class SubmissionCreate(BaseModel):
    atcoder_submission_id: int | None = None
    user_id: int
    problem_id: int
    status: str
    language: str | None = None
    execution_time_ms: int | None = None
    memory_kb: int | None = None
    score: int | None = None
    submitted_at: datetime
    notes: str | None = None


class SubmissionResponse(BaseModel):
    id: int
    atcoder_submission_id: int | None
    user_id: int
    problem_id: int
    status: str
    language: str | None
    execution_time_ms: int | None
    memory_kb: int | None
    score: int | None
    submitted_at: datetime
    notes: str | None

    model_config = {"from_attributes": True}
