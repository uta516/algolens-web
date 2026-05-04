from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.schemas.analysis import AnalysisSummary, DifficultyBucket, TagStat

router = APIRouter(prefix="/analysis", tags=["analysis"])

# AtCoder Problems の difficulty → 色 マッピング
_DIFFICULTY_BUCKETS = [
    ("灰", -float("inf"), 400),
    ("茶", 400, 800),
    ("緑", 800, 1200),
    ("水", 1200, 1600),
    ("青", 1600, 2000),
    ("黄", 2000, 2400),
    ("橙", 2400, 2800),
    ("赤", 2800, float("inf")),
]


def _difficulty_to_color(diff: float | None) -> str:
    if diff is None:
        return "不明"
    for name, lo, hi in _DIFFICULTY_BUCKETS:
        if lo <= diff < hi:
            return name
    return "赤"


@router.get("/{username}", response_model=AnalysisSummary)
def get_analysis(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.atcoder_username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    subs = (
        db.query(Submission, Problem)
        .join(Problem, Submission.problem_id == Problem.id)
        .filter(Submission.user_id == user.id)
        .all()
    )

    total = len(subs)
    ac_subs = [s for s, _ in subs if s.status == "AC"]
    ac_count = len(ac_subs)
    unique_ac = len({s.problem_id for s in ac_subs})

    # タグ別集計
    tag_map: dict[str, dict] = {}
    for sub, prob in subs:
        for tag in (prob.tags or "").split(","):
            tag = tag.strip()
            if not tag:
                continue
            if tag not in tag_map:
                tag_map[tag] = {"total": 0, "ac": 0}
            tag_map[tag]["total"] += 1
            if sub.status == "AC":
                tag_map[tag]["ac"] += 1

    tag_stats = [
        TagStat(
            tag=t,
            total=v["total"],
            ac_count=v["ac"],
            ac_rate=round(v["ac"] / v["total"], 3) if v["total"] else 0.0,
        )
        for t, v in sorted(tag_map.items(), key=lambda x: -x[1]["total"])
    ]

    # 難易度別集計
    diff_map: dict[str, dict] = {name: {"total": 0, "ac": 0} for name, *_ in _DIFFICULTY_BUCKETS}
    diff_map["不明"] = {"total": 0, "ac": 0}
    for sub, prob in subs:
        bucket = _difficulty_to_color(prob.difficulty)
        diff_map.setdefault(bucket, {"total": 0, "ac": 0})
        diff_map[bucket]["total"] += 1
        if sub.status == "AC":
            diff_map[bucket]["ac"] += 1

    order = ["灰", "茶", "緑", "水", "青", "黄", "橙", "赤", "不明"]
    difficulty_stats = [
        DifficultyBucket(bucket=b, total=diff_map[b]["total"], ac_count=diff_map[b]["ac"])
        for b in order
        if diff_map[b]["total"] > 0
    ]

    return AnalysisSummary(
        username=username,
        total_submissions=total,
        ac_count=ac_count,
        unique_ac_problems=unique_ac,
        tag_stats=tag_stats,
        difficulty_stats=difficulty_stats,
    )
