"""AtCoder 公式の問題文・解説を取得し、生データとして保存するサービス。

保存形式（data/editorials/{problem_id}/）:
  task.html              問題ページ
  samples.json           [{"input": str, "output": str}, ...]
  editorial_list.html    解説一覧ページ
  editorial_{id}.html    公式解説ページ（AtCoder 内のテキスト解説のみ）
  meta.json              問題情報と取得した解説の一覧（取得完了の目印として最後に書く）

公式/ユーザ解説の判定は、解説一覧の「公式」ラベルだけを根拠にする。
運営・作問者でもラベルなしで投稿した解説はユーザ解説として扱う。
"""

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import httpx
from bs4 import BeautifulSoup, Tag

ATCODER_BASE = "https://atcoder.jp"
EDITORIALS_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "editorials"

# 提出ページは "Mozilla/5.0 (compatible; ...)" 形式でない User-Agent を 403 で拒否するため、
# ボットの標準的な書式でツール名を名乗る（auto_reporter.py と同じ形式）
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AlgoLens/0.1; +https://github.com/uta516/algolens-web)"}
_OFFICIAL_LABELS = {"公式", "Official"}
_ALT_TITLE = re.compile(r"別解|Another", re.IGNORECASE)
_EDITORIAL_HREF = re.compile(r"^/contests/[^/]+/editorial/(\d+)$")
_SAMPLE_HEADER = re.compile(r"^(入力例|出力例)\s*(\d+)")


@dataclass(frozen=True)
class TargetProblem:
    problem_id: str
    contest_id: str
    problem_index: str
    title: str
    difficulty: float | None  # 開催直後の問題はまだ難易度がない
    tags: str


@dataclass(frozen=True)
class EditorialLink:
    editorial_id: int
    url: str
    title: str
    author: str
    is_official: bool
    editorial_type: str = ""


# ---------------------------------------------------------------------------
# HTTP クライアント
# ---------------------------------------------------------------------------

class AtCoderClient:
    """リクエスト間に最低 interval 秒の間隔を空ける HTTP クライアント。"""

    def __init__(
        self,
        interval: float = 1.5,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._client = httpx.Client(
            headers=_HEADERS, timeout=30, transport=transport, follow_redirects=True
        )

    def get(self, url: str) -> str:
        if self._last is not None:
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        try:
            resp = self._client.get(url)
        finally:
            self._last = self._clock()
        resp.raise_for_status()
        return resp.text

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# 対象問題の選定
# ---------------------------------------------------------------------------

def select_target_problems(
    contest_problems: list[dict],
    problems: list[dict],
    models: dict[str, dict],
    tags: dict[str, str],
    max_difficulty: float = 1200,
) -> list[TargetProblem]:
    """ABC の C・D 問題のうち difficulty < max_difficulty のものを返す（負の値も含む）。

    problems.json は 1 問につき 1 コンテストしか持たず、ADT で再利用された問題は
    ADT 側の contest_id / problem_index になる。そのため所属判定は contest-problem.json で行い、
    problems.json は問題名の取得にだけ使う。
    """
    names = {p["id"]: p.get("name", "") for p in problems}
    targets: dict[str, TargetProblem] = {}
    for cp in contest_problems:
        contest_id = cp["contest_id"]
        index = str(cp.get("problem_index", "")).upper()
        pid = cp["problem_id"]
        if not contest_id.startswith("abc") or index not in ("C", "D") or pid in targets:
            continue
        difficulty = models.get(pid, {}).get("difficulty")
        if difficulty is None or difficulty >= max_difficulty:
            continue
        targets[pid] = TargetProblem(
            problem_id=pid,
            contest_id=contest_id,
            problem_index=index,
            title=f"{index}. {names.get(pid, '')}".rstrip(". "),
            difficulty=float(difficulty),
            tags=tags.get(pid, ""),
        )
    return sorted(targets.values(), key=lambda t: t.problem_id)


# ---------------------------------------------------------------------------
# HTML 解析
# ---------------------------------------------------------------------------

def _normalize_sample(text: str) -> str:
    """改行を \\n に揃え、前後の空行を除いて末尾に改行を 1 つ付ける（標準入力にそのまま渡せる形）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"{text}\n" if text else ""


def _write(path: Path, text: str) -> None:
    # Windows でも改行コードを変換せず、取得したままの内容で保存する
    path.write_text(text, encoding="utf-8", newline="")


def parse_samples(task_html: str) -> list[dict]:
    """問題ページから日本語版のサンプル入出力を番号で対にして返す。"""
    soup = BeautifulSoup(task_html, "html.parser")
    root = soup.select_one("#task-statement span.lang-ja") or soup.select_one("#task-statement")
    if root is None:
        return []

    inputs: dict[int, str] = {}
    outputs: dict[int, str] = {}
    # 新しいページは <section><h3/><pre/></section>、古いページは <h3/><section><pre/></section>。
    # どちらも「見出しの次に現れる <pre>（次の見出しより前）」で取り出せる。
    for header in root.find_all(["h3", "h4"]):
        m = _SAMPLE_HEADER.match(header.get_text(strip=True))
        if not m:
            continue
        pre = header.find_next(["pre", "h3", "h4"])
        if pre is None or pre.name != "pre" or root not in pre.parents:
            continue
        target = inputs if m.group(1) == "入力例" else outputs
        target[int(m.group(2))] = _normalize_sample(pre.get_text())

    return [
        {"input": inputs[n], "output": outputs[n]}
        for n in sorted(inputs)
        if n in outputs
    ]


def parse_editorial_links(list_html: str, contest_id: str) -> list[EditorialLink]:
    """解説一覧から AtCoder 内のテキスト解説（日本語）を返す。外部リンク・動画は除外。"""
    soup = BeautifulSoup(list_html, "html.parser")
    links = []
    for li in soup.select("#main-container li"):
        if "lang-other" in (li.get("class") or []):
            continue
        anchor = next(
            (a for a in li.find_all("a", href=True) if _EDITORIAL_HREF.match(a["href"])),
            None,
        )
        if anchor is None:
            continue
        label = li.select_one("span.label")
        author = li.select_one("a.username")
        links.append(EditorialLink(
            editorial_id=int(_EDITORIAL_HREF.match(anchor["href"]).group(1)),
            url=f"{ATCODER_BASE}{anchor['href']}",
            title=anchor.get_text(" ", strip=True),
            author=author.get_text(strip=True) if author else "",
            is_official=bool(label and label.get_text(strip=True) in _OFFICIAL_LABELS),
        ))
    return links


def select_official_editorials(links: list[EditorialLink]) -> list[EditorialLink]:
    """「公式」ラベル付きの解説だけを残し、タイトルに別解とあれば alt とする。"""
    selected = []
    for link in links:
        if not link.is_official:
            continue
        etype = "alt" if _ALT_TITLE.search(link.title) else "official"
        selected.append(EditorialLink(**{**asdict(link), "editorial_type": etype}))
    return selected


def _editorial_body(soup: BeautifulSoup) -> Tag | None:
    h2 = soup.select_one("#main-container h2")
    if h2 is None:
        return None
    for div in h2.parent.find_all("div", recursive=False):
        if "clearfix" not in (div.get("class") or []):
            return div
    return None


def parse_editorial_page(editorial_html: str) -> dict:
    """解説ページからタイトルと本文 HTML を取り出す。"""
    soup = BeautifulSoup(editorial_html, "html.parser")
    h2 = soup.select_one("#main-container h2")
    body = _editorial_body(soup)
    return {
        "title": h2.get_text(" ", strip=True) if h2 else "",
        "body_html": body.decode_contents() if body else "",
    }


# ---------------------------------------------------------------------------
# 取得と保存
# ---------------------------------------------------------------------------

def problem_dir(problem_id: str, base_dir: Path = EDITORIALS_DIR) -> Path:
    return Path(base_dir) / problem_id


def load_meta(problem_id: str, base_dir: Path = EDITORIALS_DIR) -> dict | None:
    path = problem_dir(problem_id, base_dir) / "meta.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fetch_and_save_problem(
    client: AtCoderClient,
    problem: TargetProblem,
    base_dir: Path = EDITORIALS_DIR,
) -> bool:
    """問題文・サンプル・公式解説を取得して保存する。取得済みなら何もせず False を返す。"""
    pdir = problem_dir(problem.problem_id, base_dir)
    if (pdir / "meta.json").exists():
        return False
    pdir.mkdir(parents=True, exist_ok=True)

    task_url = f"{ATCODER_BASE}/contests/{problem.contest_id}/tasks/{problem.problem_id}"
    task_html = client.get(task_url)
    _write(pdir / "task.html", task_html)
    samples = parse_samples(task_html)
    _write(pdir / "samples.json", json.dumps(samples, ensure_ascii=False, indent=2))

    list_html = client.get(f"{task_url}/editorial?lang=ja")
    _write(pdir / "editorial_list.html", list_html)
    editorials = select_official_editorials(parse_editorial_links(list_html, problem.contest_id))

    for ed in editorials:
        html = client.get(f"{ed.url}?lang=ja")
        _write(pdir / f"editorial_{ed.editorial_id}.html", html)

    meta = {
        **asdict(problem),
        "url": task_url,
        "sample_count": len(samples),
        "editorials": _editorial_entries(editorials),
    }
    _write(pdir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return True


def _editorial_entries(editorials: list[EditorialLink]) -> list[dict]:
    return [
        {
            "editorial_id": ed.editorial_id,
            "url": ed.url,
            "title": ed.title,
            "author": ed.author,
            "editorial_type": ed.editorial_type,
        }
        for ed in editorials
    ]


def refresh_editorials(
    client: AtCoderClient,
    problem_id: str,
    base_dir: Path = EDITORIALS_DIR,
) -> list[dict]:
    """取得済みの問題について解説一覧を取り直し、新しく公開された公式解説を保存して meta.json を更新する。

    解説がコンテスト後しばらくして公開された問題に使う。更新後の解説一覧を返す。
    """
    meta = load_meta(problem_id, base_dir)
    if meta is None:
        raise FileNotFoundError(f"{problem_id} の meta.json がありません")
    pdir = problem_dir(problem_id, base_dir)
    task_url = meta.get("url") or f"{ATCODER_BASE}/contests/{meta['contest_id']}/tasks/{problem_id}"

    list_html = client.get(f"{task_url}/editorial?lang=ja")
    _write(pdir / "editorial_list.html", list_html)
    editorials = select_official_editorials(parse_editorial_links(list_html, meta["contest_id"]))
    for ed in editorials:
        path = pdir / f"editorial_{ed.editorial_id}.html"
        if not path.exists():
            _write(path, client.get(f"{ed.url}?lang=ja"))

    meta["editorials"] = _editorial_entries(editorials)
    _write(pdir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=2))
    return meta["editorials"]
