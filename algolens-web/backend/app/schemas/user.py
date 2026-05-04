from datetime import datetime

from pydantic import BaseModel


class UserCreate(BaseModel):
    atcoder_username: str


class UserResponse(BaseModel):
    id: int
    atcoder_username: str
    created_at: datetime

    model_config = {"from_attributes": True}
