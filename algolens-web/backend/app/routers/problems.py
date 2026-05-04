from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.problem import Problem
from app.schemas.problem import ProblemCreate, ProblemResponse

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("/", response_model=list[ProblemResponse])
def list_problems(
    contest_id: str | None = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    q = db.query(Problem)
    if contest_id:
        q = q.filter(Problem.contest_id == contest_id)
    return q.offset(skip).limit(limit).all()


@router.post("/", response_model=ProblemResponse, status_code=201)
def create_problem(body: ProblemCreate, db: Session = Depends(get_db)):
    existing = db.query(Problem).filter(Problem.atcoder_problem_id == body.atcoder_problem_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Problem already exists")
    problem = Problem(**body.model_dump())
    db.add(problem)
    db.commit()
    db.refresh(problem)
    return problem


@router.get("/{problem_id}", response_model=ProblemResponse)
def get_problem(problem_id: int, db: Session = Depends(get_db)):
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem
