from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
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
# fix_status: 修正版を提出した結果。None は「提出での確認はまだ」
FIX_CONFIRMED = "確認済み"   # 提出して AC
FIX_FAILED = "修正失敗"      # 提出して AC 以外。同じミスの回数の集計から外す


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
    # 以下は後から追加した列のため NULL 可（既存の DB には起動時に ALTER TABLE で足す）
    fix_status: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 修正版を提出した判定 AC / WA / TLE / RE
    submitted_verdict: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # 「修正失敗」の記録から作り直した場合、その元の記録
    retry_of_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("mistake_logs.id"), nullable=True)
    # 赤ペン（少ない修正）が全部の確認を通ったか。False なら「少ない修正では直せない」
    fix_found: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 赤ペンの変更の一覧（JSON: line / action / original / new / reason）
    edits: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 作り直しの記録（JSON: attempt / failed / detail。failed は落ちた確認、通れば null）
    attempt_log: Mapped[str | None] = mapped_column(Text, nullable=True)
