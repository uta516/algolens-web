from pydantic import BaseModel


class ProblemCreate(BaseModel):
    atcoder_problem_id: str
    contest_id: str
    problem_index: str
    title: str
    difficulty: float | None = None
    tags: str | None = None
    url: str | None = None


class ProblemResponse(BaseModel):
    id: int
    atcoder_problem_id: str
    contest_id: str
    problem_index: str
    title: str
    difficulty: float | None
    tags: str | None
    url: str | None

    model_config = {"from_attributes": True}
