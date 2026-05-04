from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # e.g. "abc300_c"
    atcoder_problem_id: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    # e.g. "abc300"
    contest_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # e.g. "C"
    problem_index: Mapped[str] = mapped_column(String(5), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # difficulty score from AtCoder Problems (optional)
    difficulty: Mapped[float | None] = mapped_column(Float, nullable=True)
    # comma-separated tags e.g. "DP,グラフ"
    tags: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(300), nullable=True)

    submissions: Mapped[list["Submission"]] = relationship("Submission", back_populates="problem")
