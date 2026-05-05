from pydantic import BaseModel


class ProblemSummary(BaseModel):
    title: str
    difficulty: float | None
    url: str | None


class PatternAnalysis(BaseModel):
    total_problems: int
    sample_problems: list[ProblemSummary]
    constraints_tendency: str
    frequent_algorithms: list[str]
    solving_patterns: str
    generated_at: str


class WeeklyInsights(BaseModel):
    username: str
    week_start: str
    week_end: str
    total_submissions: int
    ac_count: int
    reusable_snippets: str
    key_learnings: str
    generated_at: str
