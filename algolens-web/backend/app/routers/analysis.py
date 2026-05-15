from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.problem import Problem
from app.models.submission import Submission
from app.models.user import User
from app.schemas.analysis import AnalysisSummary, DifficultyBucket, TagStat

router = APIRouter(prefix="/analysis", tags=["analysis"])

# 灰(0-399), 茶(400-799), 緑(800-1199), 水(1200-1599),
# 青(1600-1999), 黄(2000-2399), 橙(2400-2799), 赤(2800+)
_DIFFICULTY_BUCKETS = [
    ("灰", 0, 400),
    ("茶", 400, 800),
    ("緑", 800, 1200),
    ("水", 1200, 1600),
    ("青", 1600, 2000),
    ("黄", 2000, 2400),
    ("橙", 2400, 2800),
    ("赤", 2800, float("inf")),
]
_BUCKET_ORDER = [name for name, *_ in _DIFFICULTY_BUCKETS]


def _difficulty_to_color(diff: float) -> str:
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

    # 難易度別集計 - DBに保存された difficulty を使用（外部API呼び出し不要）
    diff_map: dict[str, dict] = {name: {"total": 0, "ac": 0} for name in _BUCKET_ORDER}
    for sub, prob in subs:
        diff = prob.difficulty
        if diff is None:
            continue
        # difficulty < 0 (A/B問題など) は 0 として灰バケットに含める
        bucket = _difficulty_to_color(max(diff, 0))
        diff_map[bucket]["total"] += 1
        if sub.status == "AC":
            diff_map[bucket]["ac"] += 1

    difficulty_stats = [
        DifficultyBucket(
            bucket=b,
            total=diff_map[b]["total"],
            ac_count=diff_map[b]["ac"],
            ac_rate=round(diff_map[b]["ac"] / diff_map[b]["total"], 3) if diff_map[b]["total"] else 0.0,
        )
        for b in _BUCKET_ORDER
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
