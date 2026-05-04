"""
テスト用 fixture の定義

設計方針:
  - インメモリ SQLite (StaticPool) を使い、開発用 DB を一切汚さない
  - テーブルクリーンアップを client fixture の teardown に集約することで
    fixture 実行順序を明示的に保証する
  - StaticPool により全セッションが同一接続を共有するため、テスト中の
    コミット済みデータが別セッションから見える
"""

from pathlib import Path

# main.py の create_all が書き込む dev DB ディレクトリを事前作成
(Path(__file__).parent.parent / "data").mkdir(exist_ok=True)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app  # この import で dev engine への create_all が走る

_TEST_DB_URL = "sqlite:///:memory:"

# StaticPool: 全セッションが同一のインメモリ接続を共有する
#   → 接続ごとに別 DB になる SQLite の挙動を回避し、テスト中のデータを
#     ルーターと fixture の両方から参照できる
_test_engine = create_engine(
    _TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine)

# app.main のインポートで全モデルが Base.metadata に登録された後に実行
Base.metadata.create_all(bind=_test_engine)


def _clear_all_tables() -> None:
    """外部キー制約に配慮した逆順でテーブルを空にする。"""
    session = _TestingSession()
    try:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()
    finally:
        session.close()


@pytest.fixture
def client() -> TestClient:
    """
    get_db をテスト用セッションで差し替えた FastAPI TestClient を返す。
    teardown 時に全テーブルをクリアしてテスト間の独立性を保証する。

    使い方:
        def test_something(client: TestClient):
            resp = client.post("/users/", json={"atcoder_username": "tourist"})
    """
    def _override_get_db():
        session = _TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as tc:
        yield tc

    # teardown: オーバーライドを解除してからテーブルをクリア
    app.dependency_overrides.clear()
    _clear_all_tables()
