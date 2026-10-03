from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

MISTAKE_TYPES: tuple[str, ...] = (
    "計算量の見積もりミス",
    "境界・インデックス",
    "考察不足",
    "典型を知らない",
    "実装ミス",
    "読み違い",
)
MISTAKE_LEVELS: tuple[str, ...] = ("書き方", "考え方")


class MistakeLog(Base):
    """家庭教師の記録帳: 1 回の解説依頼につき 1 行。"""

    __tablename__ = "mistake_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # 解説ストアと同じ形式 e.g. "abc300_c"
    problem_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    original_code: Mapped[str] = mapped_column(Text, nullable=False)
    fixed_code: Mapped[str] = mapped_column(Text, nullable=False)
    diff: Mapped[str] = mapped_column(Text, nullable=False)
    # WA / TLE / RE
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    diff_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    # MISTAKE_LEVELS のいずれか
    mistake_level: Mapped[str] = mapped_column(String(10), nullable=False)
    # MISTAKE_TYPES のいずれか
    mistake_type: Mapped[str] = mapped_column(String(30), index=True, nullable=False)
    # サンプルがなく確認を飛ばした場合は None
    samples_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gap_summary: Mapped[str] = mapped_column(Text, nullable=False)
    correct_idea: Mapped[str] = mapped_column(Text, nullable=False)
    lesson: Mapped[str] = mapped_column(Text, nullable=False)
