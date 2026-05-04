"""routers/users.py のテスト

カバー範囲:
  - POST /users/  : 正常作成 / 重複エラー(409)
  - GET  /users/{username} : 正常取得 / 存在しないユーザー(404)
"""

from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# POST /users/
# ---------------------------------------------------------------------------

class TestCreateUser:
    def test_success_returns_201(self, client: TestClient):
        resp = client.post("/users/", json={"atcoder_username": "tourist"})

        assert resp.status_code == 201

    def test_success_response_body(self, client: TestClient):
        resp = client.post("/users/", json={"atcoder_username": "tourist"})
        data = resp.json()

        assert data["atcoder_username"] == "tourist"
        assert isinstance(data["id"], int)
        assert "created_at" in data

    def test_duplicate_username_returns_409(self, client: TestClient):
        client.post("/users/", json={"atcoder_username": "tourist"})

        resp = client.post("/users/", json={"atcoder_username": "tourist"})

        assert resp.status_code == 409

    def test_different_usernames_can_coexist(self, client: TestClient):
        r1 = client.post("/users/", json={"atcoder_username": "tourist"})
        r2 = client.post("/users/", json={"atcoder_username": "chokudai"})

        assert r1.status_code == 201
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]


# ---------------------------------------------------------------------------
# GET /users/{username}
# ---------------------------------------------------------------------------

class TestGetUser:
    def test_success_returns_200(self, client: TestClient):
        client.post("/users/", json={"atcoder_username": "chokudai"})

        resp = client.get("/users/chokudai")

        assert resp.status_code == 200

    def test_success_response_body(self, client: TestClient):
        client.post("/users/", json={"atcoder_username": "chokudai"})

        data = client.get("/users/chokudai").json()

        assert data["atcoder_username"] == "chokudai"
        assert isinstance(data["id"], int)

    def test_not_found_returns_404(self, client: TestClient):
        resp = client.get("/users/no_such_user_xyz")

        assert resp.status_code == 404

    def test_created_user_is_retrievable(self, client: TestClient):
        """作成したユーザーが GET で取得できることを一連の流れで確認する。"""
        created = client.post("/users/", json={"atcoder_username": "rng_58"}).json()
        fetched = client.get("/users/rng_58").json()

        assert created["id"] == fetched["id"]
        assert created["atcoder_username"] == fetched["atcoder_username"]
