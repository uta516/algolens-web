"""AtCoder Problems の公開API を使って提出データを取得するサービス。

AtCoder Problems API (非公式・公開):
  - 提出一覧: https://kenkoooo.com/atcoder/atcoder-api/v3/user/submissions?user=<user>&from_second=<epoch>
  - 問題情報: https://kenkoooo.com/atcoder/resources/problems.json
  - 難易度:   https://kenkoooo.com/atcoder/resources/problem-models.json
"""

from datetime import datetime

import httpx

_BASE = "https://kenkoooo.com/atcoder"
_HEADERS = {"User-Agent": "AlgoLens/0.1 (https://github.com/your-repo)"}


def fetch_user_submissions(username: str, from_second: int = 0) -> list[dict]:
    """指定ユーザーの提出データをAtCoder Problems APIから取得する。"""
    url = f"{_BASE}/atcoder-api/v3/user/submissions"
    params = {"user": username, "from_second": from_second}
    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    return resp.json()


def fetch_problems() -> list[dict]:
    """全問題リストを取得する。"""
    url = f"{_BASE}/resources/problems.json"
    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return resp.json()


def fetch_problem_models() -> dict:
    """難易度データを取得する（problem_id → {"difficulty": float, ...}）。"""
    url = f"{_BASE}/resources/problem-models.json"
    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        resp = client.get(url)
        resp.raise_for_status()
    return resp.json()


def fetch_problem_tags() -> dict[str, list[str]]:
    """タグ情報を取得する (problem_id → [tag, ...])。失敗時は空辞書を返す。

    AtCoder Problems が公開している problem-tags.json を使用。
    レスポンス形式が変わっても壊れないよう list / dict 両方に対応する。
    """
    url = f"{_BASE}/resources/problem-tags.json"
    try:
        with httpx.Client(headers=_HEADERS, timeout=30) as client:
            resp = client.get(url)
            resp.raise_for_status()
        raw = resp.json()
        result: dict[str, list[str]] = {}
        if isinstance(raw, list):
            for item in raw:
                pid = str(item.get("problem_id", "")).lower()
                tags = item.get("tags") or []
                if pid and isinstance(tags, list) and tags:
                    result[pid] = [str(t) for t in tags]
        elif isinstance(raw, dict):
            for pid, val in raw.items():
                key = pid.lower()
                if isinstance(val, list):
                    result[key] = [str(t) for t in val]
                elif isinstance(val, dict):
                    tags = val.get("tags", [])
                    if isinstance(tags, list):
                        result[key] = [str(t) for t in tags]
        return result
    except Exception:
        return {}


def normalize_submission(raw: dict) -> dict:
    """API レスポンスを DB 登録用の辞書に変換する。"""
    return {
        "atcoder_submission_id": raw.get("id"),
        "status": raw.get("result", ""),
        "language": raw.get("language"),
        "execution_time_ms": raw.get("execution_time"),
        "memory_kb": raw.get("memory"),
        "score": raw.get("point"),
        "submitted_at": datetime.utcfromtimestamp(raw["epoch_second"]),
        # problem_id は別途 DB ルックアップが必要
        "_atcoder_problem_id": f"{raw['contest_id']}_{raw['problem_id']}".lower(),
    }
