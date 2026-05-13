from pydantic import BaseModel


class SnippetCreate(BaseModel):
    title: str
    tags: str = ""
    code: str = ""
    memo: str = ""
    category: str = "my_snippet"


class SnippetUpdate(BaseModel):
    title: str
    tags: str = ""
    code: str = ""
    memo: str = ""
    category: str = "my_snippet"


class Snippet(SnippetCreate):
    id: str  # UUID
    created_at: str


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


class StudyGuide(BaseModel):
    username: str
    current_weakness: str
    required_code_pattern: str
    recommended_practice: str
    generated_at: str
