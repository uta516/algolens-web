from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/", response_model=UserResponse, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.atcoder_username == body.atcoder_username).first()
    if existing:
        raise HTTPException(status_code=409, detail="Username already registered")
    user = User(atcoder_username=body.atcoder_username)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{username}", response_model=UserResponse)
def get_user(username: str, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.atcoder_username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user
