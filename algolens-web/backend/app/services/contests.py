"""コンテストの一覧（AtCoder Problems）と、終了済みかどうかの判定。

AtCoder の生成 AI の利用ルールを守るため、振り返り・家庭教師はコンテスト終了後だけ使えるようにする。
"""

import time

import httpx

CONTESTS_URL = "https://kenkoooo.com/atcoder/resources/contests.json"
_CACHE_TTL_SEC = 3600
_cache: dict[str, tuple[float, list[dict]]] = {}

NOT_FINISHED_MESSAGE = "コンテスト終了後に使ってください（AtCoder の生成 AI の利用ルールのため）"
UNKNOWN_MESSAGE = "コンテストの終了時刻を確認できないため使えません。終了後にもう一度お試しください"


def fetch_contests() -> list[dict]:
    """contests.json（1 時間キャッシュ）。"""
    hit = _cache.get("contests")
    if hit and time.time() - hit[0] < _CACHE_TTL_SEC:
        return hit[1]
    # kenkoooo.com はまれに接続を切ることがあるため、接続エラーだけ少し待って取り直す
    for wait in (2, 5, None):
        try:
            resp = httpx.get(CONTESTS_URL, timeout=60)
            break
        except httpx.TransportError:
            if wait is None:
                raise
            time.sleep(wait)
    resp.raise_for_status()
    contests = resp.json()
    _cache["contests"] = (time.time(), contests)
    return contests


def find_contest(contest_id: str, contests: list[dict] | None = None) -> dict | None:
    contests = fetch_contests() if contests is None else contests
    return next((c for c in contests if c["id"] == contest_id), None)


def contest_end_epoch(contest: dict) -> int:
    return int(contest["start_epoch_second"]) + int(contest.get("duration_second", 0))


def finished_error(contest: dict | None, now: float | None = None) -> str | None:
    """終了済みなら None、使えないならその理由を返す。

    一覧にない（開催前で未登録・ID の誤りなど）場合は、終了を確認できないので使えないものとする。
    """
    if contest is None:
        return UNKNOWN_MESSAGE
    now = time.time() if now is None else now
    if now < contest_end_epoch(contest):
        return NOT_FINISHED_MESSAGE
    return None


def is_finished(contest_id: str, now: float | None = None) -> bool:
    """終了済みと確認できたら True（取得に失敗したら False）。"""
    try:
        return finished_error(find_contest(contest_id), now) is None
    except httpx.HTTPError:
        return False
