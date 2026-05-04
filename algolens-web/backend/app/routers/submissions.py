from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.submission import Submission
from app.schemas.submission import SubmissionCreate, SubmissionResponse

router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("/", response_model=list[SubmissionResponse])
def list_submissions(
    user_id: int | None = Query(None),
    problem_id: int | None = Query(None),
    status: str | None = Query(None),
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    q = db.query(Submission)
    if user_id:
        q = q.filter(Submission.user_id == user_id)
    if problem_id:
        q = q.filter(Submission.problem_id == problem_id)
    if status:
        q = q.filter(Submission.status == status)
    return q.order_by(Submission.submitted_at.desc()).offset(skip).limit(limit).all()


@router.post("/", response_model=SubmissionResponse, status_code=201)
def create_submission(body: SubmissionCreate, db: Session = Depends(get_db)):
    submission = Submission(**body.model_dump())
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


@router.get("/{submission_id}", response_model=SubmissionResponse)
def get_submission(submission_id: int, db: Session = Depends(get_db)):
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    return sub
