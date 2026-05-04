from pydantic import BaseModel


class TagStat(BaseModel):
    tag: str
    total: int
    ac_count: int
    ac_rate: float


class DifficultyBucket(BaseModel):
    bucket: str  # e.g. "灰", "茶", "緑", "水", "青", "黄", "橙", "赤"
    total: int
    ac_count: int


class AnalysisSummary(BaseModel):
    username: str
    total_submissions: int
    ac_count: int
    unique_ac_problems: int
    tag_stats: list[TagStat]
    difficulty_stats: list[DifficultyBucket]
