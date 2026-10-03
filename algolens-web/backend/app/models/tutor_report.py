from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# status: 取り込み時に pending で作り、1 問処理し終えたら done にする
REPORT_PENDING = "pending"
REPORT_DONE = "done"
# kind: 判定ごとの処理の種類
KIND_MISTAKE = "mistake"   # WA / TLE / RE → 家庭教師の解説
KIND_AC = "ac"             # AC → もっと簡単・速い解き方の提案
KIND_SKIPPED = "skipped"   # CE など → 対象外


class TutorReport(Base):
    """振り返り: コンテストの問題ごとに、最後の提出 1 つについての結果を 1 行で持つ。"""

    __tablename__ = "tutor_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    contest_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # 解説ストアと同じ形式 e.g. "abc300_c"
    problem_id: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    problem_index: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # 同じ提出は作り直さないための一意キー
    submission_id: Mapped[int] = mapped_column(Integer, unique=True, index=True, nullable=False)
    verdict: Mapped[str] = mapped_column(String(10), nullable=False)
    language: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    submitted_at: Mapped[int] = mapped_column(Integer, nullable=False)  # epoch 秒
    # 最後の提出より前の WA / TLE / RE の回数
    wa_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[str] = mapped_column(String(10), nullable=False, default=REPORT_PENDING)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    original_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 表示用の結果一式（JSON）。kind ごとに中身が違う
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 公式解説が公開済みだったか（未処理・対象外は None）
    editorial_available: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    mistake_log_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("mistake_logs.id"), nullable=True)
    gemini_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 直近の失敗理由（pending のまま残り、次回やり直す）
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
