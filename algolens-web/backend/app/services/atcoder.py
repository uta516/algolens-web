import httpx

_BASE = "https://kenkoooo.com/atcoder"
_HEADERS = {"User-Agent": "AlgoLens/0.1"}


def fetch_problem_models() -> dict[str, dict]:
    """全問題の推測難易度データを返す。

    Returns:
        {"problem_id": {"difficulty": float, ...}, ...}
    """
    url = f"{_BASE}/resources/problem-models.json"
    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return resp.json()
