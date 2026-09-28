"""editorial_scraper のテスト（ネットワークには接続しない）。"""

import json
from pathlib import Path

import httpx
import pytest

from app.services.editorial_scraper import (
    AtCoderClient,
    EditorialLink,
    TargetProblem,
    fetch_and_save_problem,
    parse_editorial_links,
    parse_editorial_page,
    parse_samples,
    select_official_editorials,
    select_target_problems,
)

FIXTURES = Path(__file__).parent / "fixtures" / "atcoder"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# サンプル入出力
# ---------------------------------------------------------------------------

def test_parse_samples_pairs_inputs_and_outputs_by_number():
    samples = parse_samples(_read("task_sample.html"))

    # 英語版のサンプルは含めず、出力例の後ろの説明文も含めない
    assert samples == [
        {"input": "3\n1 2 3\n", "output": "6\n"},
        {"input": "1\n5\n", "output": "5\n"},
        {"input": "2\n-1 1\n", "output": "0\n"},
    ]


def test_parse_samples_accepts_header_without_space_and_skips_unpaired():
    html = """
    <div id="task-statement"><span class="lang"><span class="lang-ja">
      <section><h3>入力例1</h3><pre>1 2</pre></section>
      <section><h3>出力例1</h3><pre>3</pre><p>説明</p></section>
      <section><h3>入力例2</h3><pre>5 5</pre></section>
    </span><span class="lang-en">
      <section><h3>Sample Input 1</h3><pre>1 2</pre></section>
    </span></span></div>
    """
    assert parse_samples(html) == [{"input": "1 2\n", "output": "3\n"}]


def test_parse_samples_normalizes_newlines():
    html = (
        '<div id="task-statement"><h3>入力例 1</h3><pre>\r\n\r\n1\r\n2\r\n\r\n</pre>'
        '<h3>出力例 1</h3><pre>3</pre></div>'
    )
    assert parse_samples(html) == [{"input": "1\n2\n", "output": "3\n"}]


def test_parse_samples_supports_old_layout_heading_outside_section():
    # abc001〜 の古い問題ページは <h3> が <section> の外にあり、lang-ja もない
    html = """
    <div id="task-statement">
      <div class="part"><h3>入力例 1</h3><section><pre>1 2</pre></section></div>
      <div class="part"><h3>出力例 1</h3><section><pre>3</pre></section></div>
      <div class="part"><h3>入力例 2</h3><section><p>説明のみ</p></section></div>
      <div class="part"><h3>出力例 2</h3><section><pre>9</pre></section></div>
    </div>
    """
    assert parse_samples(html) == [{"input": "1 2\n", "output": "3\n"}]


# ---------------------------------------------------------------------------
# 解説一覧
# ---------------------------------------------------------------------------

def test_parse_editorial_links_keeps_only_internal_japanese_editorials():
    links = parse_editorial_links(_read("editorial_list_sample.html"), contest_id="abc999")

    ids = [link.editorial_id for link in links]
    # 動画・外部ブログ（/jump?url=...）と英語版（lang-other）は含まれない
    assert ids == [1001, 1003, 1004]
    assert links[0].is_official is True
    assert links[0].author == "writer_a"
    assert links[0].title == "解説"
    assert links[0].url == "https://atcoder.jp/contests/abc999/editorial/1001"
    # ラベルなしの別解は、運営の投稿でもユーザ解説扱い
    assert links[1].is_official is False
    assert links[2].is_official is False
    assert links[2].author == "staff_b"


def test_parse_editorial_links_excludes_other_language():
    html = """
    <div id="main-container"><ul>
      <li class="hidden lang-other"><span class="label label-default">Official</span>
        <a href="/contests/abc1/editorial/1">Editorial</a> by <a class="username" href="/users/x">x</a></li>
      <li><span class="label label-default">公式</span>
        <a href="/contests/abc1/editorial/2">解説</a> by <a class="username" href="/users/y">y</a></li>
    </ul></div>
    """
    links = parse_editorial_links(html, contest_id="abc1")
    assert [link.editorial_id for link in links] == [2]


def _link(eid: int, title: str, official: bool) -> EditorialLink:
    return EditorialLink(
        editorial_id=eid,
        url=f"https://atcoder.jp/contests/abc1/editorial/{eid}",
        title=title,
        author="someone",
        is_official=official,
    )


def test_select_official_editorials_drops_user_editorials_and_marks_alt():
    selected = select_official_editorials([
        _link(1, "解説", True),
        _link(2, "別解", False),
        _link(3, "別解（二分探索）", True),
    ])

    assert [(e.editorial_id, e.editorial_type) for e in selected] == [
        (1, "official"),
        (3, "alt"),
    ]


# ---------------------------------------------------------------------------
# 解説本文ページ
# ---------------------------------------------------------------------------

def test_parse_editorial_page_extracts_title_and_body():
    page = parse_editorial_page(_read("editorial_no_headings.html"))

    assert page["title"] == "C - Sample Sum Editorial by writer_a"
    assert "想定解では次の性質を使います" in page["body_html"]
    # 投稿日時などのフッタは本文に含めない
    assert "last update" not in page["body_html"]


# ---------------------------------------------------------------------------
# 対象問題の選定
# ---------------------------------------------------------------------------

def test_select_target_problems_filters_abc_c_d_under_1200_including_negative():
    # contest-problem.json: 1 問が複数コンテスト（ADT など）に属する
    contest_problems = [
        {"contest_id": "abc300", "problem_id": "abc300_c", "problem_index": "C"},
        {"contest_id": "adt_all_20231205_2", "problem_id": "abc300_c", "problem_index": "E"},
        {"contest_id": "abc300", "problem_id": "abc300_d", "problem_index": "D"},
        {"contest_id": "abc300", "problem_id": "abc300_e", "problem_index": "E"},
        {"contest_id": "abc301", "problem_id": "abc301_c", "problem_index": "C"},
        {"contest_id": "abc302", "problem_id": "abc302_c", "problem_index": "C"},
        {"contest_id": "arc100", "problem_id": "arc100_c", "problem_index": "C"},
        {"contest_id": "abc010", "problem_id": "abc010_3", "problem_index": "C"},
    ]
    # problems.json: 問題名（contest_id / problem_index は ADT 側になっていることがある）
    problems = [
        {"id": "abc300_c", "contest_id": "adt_all_20231205_2", "problem_index": "E", "name": "Sample"},
        {"id": "abc300_d", "contest_id": "abc300", "problem_index": "D", "name": "X"},
        {"id": "abc010_3", "contest_id": "abc010", "problem_index": "C", "name": "Old"},
    ]
    models = {
        "abc300_c": {"difficulty": 500.0},
        "abc300_d": {"difficulty": 1199.9},
        "abc300_e": {"difficulty": 300.0},
        "abc301_c": {"difficulty": 1200.0},
        "arc100_c": {"difficulty": 100.0},
        "abc010_3": {"difficulty": -150.0},
    }
    tags = {"abc300_c": "全探索,実装"}

    targets = select_target_problems(contest_problems, problems, models, tags)

    assert [t.problem_id for t in targets] == ["abc010_3", "abc300_c", "abc300_d"]
    assert targets[1] == TargetProblem(
        problem_id="abc300_c",
        contest_id="abc300",
        problem_index="C",
        title="C. Sample",
        difficulty=500.0,
        tags="全探索,実装",
    )
    assert targets[0].tags == ""
    assert targets[0].difficulty == -150.0


# ---------------------------------------------------------------------------
# HTTP クライアント（アクセス間隔）
# ---------------------------------------------------------------------------

class _FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_client_waits_between_requests():
    clock = _FakeClock()
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text="ok"))
    client = AtCoderClient(interval=1.5, transport=transport, clock=clock.time, sleep=clock.sleep)

    client.get("https://atcoder.jp/a")
    clock.now += 0.5
    client.get("https://atcoder.jp/b")

    assert clock.sleeps == [pytest.approx(1.0)]


def test_client_raises_on_error_status():
    transport = httpx.MockTransport(lambda req: httpx.Response(404))
    client = AtCoderClient(interval=0, transport=transport)
    with pytest.raises(httpx.HTTPStatusError):
        client.get("https://atcoder.jp/missing")


# ---------------------------------------------------------------------------
# 取得して保存（取得済みはスキップ）
# ---------------------------------------------------------------------------

def _router(requested: list[str]):
    pages = {
        "/contests/abc999/tasks/abc999_c": _read("task_sample.html"),
        "/contests/abc999/tasks/abc999_c/editorial": _read("editorial_list_sample.html"),
        "/contests/abc999/editorial/1001": _read("editorial_no_headings.html"),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        body = pages.get(request.url.path)
        return httpx.Response(200, text=body) if body else httpx.Response(404)

    return handler


_PROBLEM = TargetProblem(
    problem_id="abc999_c", contest_id="abc999", problem_index="C",
    title="C. Sample Sum", difficulty=500.0, tags="全探索",
)


def test_fetch_and_save_problem_writes_raw_files(tmp_path):
    requested: list[str] = []
    client = AtCoderClient(interval=0, transport=httpx.MockTransport(_router(requested)))

    fetched = fetch_and_save_problem(client, _PROBLEM, tmp_path)

    assert fetched is True
    pdir = tmp_path / "abc999_c"
    assert (pdir / "task.html").exists()
    assert (pdir / "editorial_1001.html").exists()
    # ユーザ解説・英語版は取得しない
    assert sorted(p.name for p in pdir.glob("editorial_*.html")) == [
        "editorial_1001.html",
        "editorial_list.html",
    ]

    samples = json.loads((pdir / "samples.json").read_text(encoding="utf-8"))
    assert len(samples) == 3

    meta = json.loads((pdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["problem_id"] == "abc999_c"
    assert meta["difficulty"] == 500.0
    assert meta["tags"] == "全探索"
    assert meta["sample_count"] == 3
    assert meta["editorials"] == [{
        "editorial_id": 1001,
        "url": "https://atcoder.jp/contests/abc999/editorial/1001",
        "title": "解説",
        "author": "writer_a",
        "editorial_type": "official",
    }]


def test_fetch_and_save_problem_skips_already_fetched(tmp_path):
    requested: list[str] = []
    client = AtCoderClient(interval=0, transport=httpx.MockTransport(_router(requested)))

    fetch_and_save_problem(client, _PROBLEM, tmp_path)
    requested.clear()
    fetched = fetch_and_save_problem(client, _PROBLEM, tmp_path)

    assert fetched is False
    assert requested == []
