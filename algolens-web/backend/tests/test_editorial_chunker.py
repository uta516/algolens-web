"""editorial_chunker のテスト。"""

import json
from pathlib import Path

from app.services.editorial_chunker import (
    chunk_editorial,
    extract_body_text,
    get_problem_body_text,
)
from app.services.editorial_scraper import parse_editorial_page

FIXTURES = Path(__file__).parent / "fixtures" / "atcoder"


def _body(name: str) -> str:
    return parse_editorial_page((FIXTURES / name).read_text(encoding="utf-8"))["body_html"]


# ---------------------------------------------------------------------------
# 見出しによる分割
# ---------------------------------------------------------------------------

def test_real_headings_define_sections():
    html = """
    <h3>考察</h3><p>まず全探索を考えます。</p>
    <h3>解法</h3><p>二分探索で境界を求めます。</p>
    <h3>計算量</h3><p>O(N log N) です。</p>
    """
    chunks = chunk_editorial(html)

    assert [(c.section, c.heading) for c in chunks] == [
        ("observation", "考察"),
        ("solution", "解法"),
        ("complexity", "計算量"),
    ]
    assert chunks[1].text == "二分探索で境界を求めます。"
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_short_keyword_paragraph_is_treated_as_heading():
    html = (
        "<p>方針</p><p>累積和を使います。</p><p><strong>計算量</strong></p><p>O(N)</p>"
        "<p>考察：</p><p>単調性があります。</p>"
    )
    chunks = chunk_editorial(html)
    assert [(c.section, c.text) for c in chunks] == [
        ("solution", "累積和を使います。"),
        ("complexity", "O(N)"),
        ("observation", "単調性があります。"),
    ]


def test_sentence_starting_with_keyword_is_not_heading():
    chunks = chunk_editorial("<p>想定解では次の性質を使います。</p><p>続き。</p>")
    assert [(c.section, c.text) for c in chunks] == [("body", "想定解では次の性質を使います。\n続き。")]


def test_unknown_heading_becomes_other_and_leading_text_is_body():
    html = "<p>導入の文章。</p><h3>おまけ</h3><p>補足。</p>"
    chunks = chunk_editorial(html)
    assert [(c.section, c.heading) for c in chunks] == [("body", ""), ("other", "おまけ")]


# ---------------------------------------------------------------------------
# 見出しがない解説（AtCoder の実ページと同じ構造の自作 HTML）
# ---------------------------------------------------------------------------

def test_editorial_without_headings_separates_code_from_body():
    chunks = chunk_editorial(_body("editorial_no_headings.html"))
    sections = [c.section for c in chunks]

    assert "body" in sections
    code = [c for c in chunks if c.section == "code"]
    assert len(code) == 1
    assert "#include <iostream>" in code[0].text
    assert code[0].heading == "実装例(C++)"

    body_text = "\n".join(c.text for c in chunks if c.section == "body")
    # 短い図（#.# のパターン）はコードではなく本文として残る
    assert "#.#" in body_text
    # インライン数式が改行で分断されない
    assert r"大きさ \(1\) の小さな模様" in body_text
    # 「計算量は〜です。」は文なので見出しにならず本文に残る
    assert r"計算量は \(\mathrm{O}(HW)\) です。" in body_text
    assert "#include" not in body_text


def test_details_proof_is_separate_section():
    chunks = chunk_editorial(_body("editorial_with_proof.html"))

    proof = [c for c in chunks if c.section == "proof"]
    assert len(proof) == 1
    assert "架空の証明" in proof[0].text
    body = "\n".join(c.text for c in chunks if c.section == "body")
    assert "連結成分" in body
    assert "架空の証明" not in body


def test_long_section_is_split_under_max_chars():
    sentences = "".join(f"これは{i}番目の文です。" for i in range(200))
    html = f"<p>{sentences}</p><p>{sentences}</p>"

    chunks = chunk_editorial(html, max_chars=300)

    assert len(chunks) > 2
    assert all(len(c.text) <= 300 for c in chunks)
    assert all(c.section == "body" for c in chunks)
    assert "".join(c.text for c in chunks).count("番目の文です。") == 400


def test_empty_body_returns_no_chunks():
    assert chunk_editorial("<p>  </p>") == []


# ---------------------------------------------------------------------------
# 本文（コード・証明を除く）の取り出し
# ---------------------------------------------------------------------------

def test_extract_body_text_excludes_code_and_proof():
    text = extract_body_text(_body("editorial_with_proof.html"))
    assert "連結成分" in text
    assert "架空の証明" not in text

    text2 = extract_body_text(_body("editorial_no_headings.html"))
    assert "想定解" in text2
    assert "#include" not in text2


def _save_problem(base: Path, editorials: list[tuple[int, str, str]]) -> None:
    pdir = base / "abc999_c"
    pdir.mkdir(parents=True)
    meta = {"problem_id": "abc999_c", "editorials": []}
    for eid, etype, body in editorials:
        (pdir / f"editorial_{eid}.html").write_text(
            f'<div id="main-container"><div class="col-sm-12">'
            f'<span class="label">公式</span><h2>C - X Editorial</h2><hr/>'
            f'<div>{body}</div><div class="clearfix">posted</div></div></div>',
            encoding="utf-8",
        )
        meta["editorials"].append({"editorial_id": eid, "editorial_type": etype})
    (pdir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")


def test_get_problem_body_text_joins_official_editorials_only(tmp_path):
    _save_problem(tmp_path, [
        (1, "official", "<p>本解の説明。</p><details><summary>証明</summary><p>証明の中身。</p></details>"),
        (2, "alt", "<p>別解の説明。</p>"),
        (3, "official", "<p>二つ目の公式解説。</p><pre>" + "int x;\n" * 10 + "</pre>"),
    ])

    text = get_problem_body_text("abc999_c", tmp_path)

    assert "本解の説明。" in text
    assert "二つ目の公式解説。" in text
    assert "別解の説明。" not in text
    assert "証明の中身。" not in text
    assert "int x;" not in text


def test_get_problem_body_text_returns_empty_for_unknown_problem(tmp_path):
    assert get_problem_body_text("abc000_c", tmp_path) == ""
