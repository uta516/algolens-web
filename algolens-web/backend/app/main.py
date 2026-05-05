from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import Base, engine
from app.routers import analysis, knowledge, problems, submissions, sync, users

# テーブルを自動作成（Alembicに移行するまでの暫定）
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="AlgoLens API",
    description="AtCoder 学習最適化アプリのバックエンドAPI",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501"],  # Streamlit dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(users.router)
app.include_router(problems.router)
app.include_router(submissions.router)
app.include_router(analysis.router)
app.include_router(knowledge.router)
app.include_router(sync.router)


@app.get("/health")
def health():
    return {"status": "ok"}
