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

_PAGE_SIZE = 500  # AtCoder Problems API の1ページあたり上限件数


def fetch_user_submissions(username: str, from_second: int = 0) -> list[dict]:
    """指定ユーザーの全提出データをAtCoder Problems APIから取得する（ページネーション対応）。

    API は1リクエストあたり最大 _PAGE_SIZE 件を古い順に返す。
    返却件数が 0 件になるまでループし、from_second を更新しながら全ページを取得する。
    """
    url = f"{_BASE}/atcoder-api/v3/user/submissions"
    all_subs: list[dict] = []
    current_from = from_second
    page = 1

    with httpx.Client(headers=_HEADERS, timeout=30) as client:
        while True:
            params = {"user": username, "from_second": current_from}
            resp = client.get(url, params=params)
            resp.raise_for_status()
            batch: list[dict] = resp.json()

            # 0 件になったら終了（これが唯一の終了条件）
            if not batch:
                print(f"[INFO] fetch_user_submissions: page={page} で 0件 → 取得完了")
                break

            all_subs.extend(batch)
            print(f"[INFO] fetch_user_submissions: page={page}, {len(batch)}件取得 "
                  f"(from_second={current_from}, 累計={len(all_subs)})")

            # 次ページ: 最後の提出の epoch_second + 1 から取得
            current_from = max(s["epoch_second"] for s in batch) + 1
            page += 1

    # epoch_second 境界の重複を ID で除去
    seen: set[int] = set()
    unique: list[dict] = []
    for sub in all_subs:
        sid = sub.get("id")
        if sid not in seen:
            seen.add(sid)
            unique.append(sub)

    print(f"[INFO] fetch_user_submissions: 全{len(unique)}件取得完了（重複除去後）")
    return unique


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
    except Exception as e:
        print(f"[WARN] fetch_problem_tags: 外部タグAPI取得失敗 → シードタグにフォールバックします。原因: {e}")
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
