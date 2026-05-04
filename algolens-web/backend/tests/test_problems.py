"""routers/problems.py のテスト

カバー範囲:
  - POST /problems/            : 正常作成 / 重複エラー(409)
  - GET  /problems/            : 全件取得 / contest_id フィルター
  - GET  /problems/{problem_id}: 正常取得 / 存在しない問題(404)
"""

from fastapi.testclient import TestClient

# テストで使い回す問題ペイロード（辞書なので必要に応じて上書きコピー可能）
_ABC300_C = {
    "atcoder_problem_id": "abc300_c",
    "contest_id": "abc300",
    "problem_index": "C",
    "title": "Fibonacci",
    "difficulty": 1200.0,
    "tags": "DP",
    "url": "https://atcoder.jp/contests/abc300/tasks/abc300_c",
}

_ABC200_A = {
    "atcoder_problem_id": "abc200_a",
    "contest_id": "abc200",
    "problem_index": "A",
    "title": "Beginner",
    "difficulty": 100.0,
    "tags": "実装",
    "url": "https://atcoder.jp/contests/abc200/tasks/abc200_a",
}


# ---------------------------------------------------------------------------
# POST /problems/
# ---------------------------------------------------------------------------

class TestCreateProblem:
    def test_success_returns_201(self, client: TestClient):
        resp = client.post("/problems/", json=_ABC300_C)

        assert resp.status_code == 201

    def test_success_response_body(self, client: TestClient):
        data = client.post("/problems/", json=_ABC300_C).json()

        assert data["atcoder_problem_id"] == "abc300_c"
        assert data["contest_id"] == "abc300"
        assert data["problem_index"] == "C"
        assert data["title"] == "Fibonacci"
        assert data["difficulty"] == 1200.0
        assert data["tags"] == "DP"
        assert isinstance(data["id"], int)

    def test_optional_fields_can_be_null(self, client: TestClient):
        payload = {
            "atcoder_problem_id": "abc300_d",
            "contest_id": "abc300",
            "problem_index": "D",
            "title": "Grid",
        }

        data = client.post("/problems/", json=payload).json()

        assert data["difficulty"] is None
        assert data["tags"] is None
        assert data["url"] is None

    def test_duplicate_problem_id_returns_409(self, client: TestClient):
        client.post("/problems/", json=_ABC300_C)

        resp = client.post("/problems/", json=_ABC300_C)

        assert resp.status_code == 409


# ---------------------------------------------------------------------------
# GET /problems/
# ---------------------------------------------------------------------------

class TestListProblems:
    def test_empty_returns_empty_list(self, client: TestClient):
        resp = client.get("/problems/")

        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_all_problems(self, client: TestClient):
        client.post("/problems/", json=_ABC300_C)
        client.post("/problems/", json=_ABC200_A)

        problems = client.get("/problems/").json()

        assert len(problems) == 2

    def test_filter_by_contest_id(self, client: TestClient):
        client.post("/problems/", json=_ABC300_C)
        client.post("/problems/", json=_ABC200_A)

        resp = client.get("/problems/", params={"contest_id": "abc300"})
        problems = resp.json()

        assert len(problems) == 1
        assert problems[0]["contest_id"] == "abc300"

    def test_filter_by_contest_id_no_match(self, client: TestClient):
        client.post("/problems/", json=_ABC300_C)

        problems = client.get("/problems/", params={"contest_id": "abc999"}).json()

        assert problems == []

    def test_limit_parameter(self, client: TestClient):
        client.post("/problems/", json=_ABC300_C)
        client.post("/problems/", json=_ABC200_A)

        problems = client.get("/problems/", params={"limit": 1}).json()

        assert len(problems) == 1


# ---------------------------------------------------------------------------
# GET /problems/{problem_id}
# ---------------------------------------------------------------------------

class TestGetProblem:
    def test_success_returns_200(self, client: TestClient):
        created = client.post("/problems/", json=_ABC300_C).json()

        resp = client.get(f"/problems/{created['id']}")

        assert resp.status_code == 200

    def test_success_response_body(self, client: TestClient):
        created = client.post("/problems/", json=_ABC300_C).json()

        data = client.get(f"/problems/{created['id']}").json()

        assert data["id"] == created["id"]
        assert data["atcoder_problem_id"] == "abc300_c"

    def test_not_found_returns_404(self, client: TestClient):
        resp = client.get("/problems/99999")

        assert resp.status_code == 404

    def test_created_problem_is_retrievable(self, client: TestClient):
        """POST で作成した問題が GET /problems/{id} で取得できることを確認。"""
        created = client.post("/problems/", json=_ABC300_C).json()
        fetched = client.get(f"/problems/{created['id']}").json()

        assert created["atcoder_problem_id"] == fetched["atcoder_problem_id"]
        assert created["difficulty"] == fetched["difficulty"]
