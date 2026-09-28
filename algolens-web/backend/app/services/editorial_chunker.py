"""公式解説の本文 HTML をチャンクに分割する。

AtCoder の解説は見出しタグを持たないものが多いため、次の順で区切りを決める。
  1. h1〜h6 の見出し
  2. 「考察」「解法」「計算量」「実装例」などで始まる短い段落（疑似見出し）
  3. 見出しがなければ全体を section="body" とし、max_chars ごとに分割
コード（実装例の <pre>）は section="code"、<details> の証明は section="proof" として分ける。
"""

import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

from app.services.editorial_scraper import EDITORIALS_DIR, load_meta, parse_editorial_page, problem_dir

DEFAULT_MAX_CHARS = 500
# 本文として扱わないセクション（extract_body_text で除外）
_NON_BODY_SECTIONS = {"code", "proof"}

_SECTION_KEYWORDS: list[tuple[str, str]] = [
    (r"考察|観察|着眼", "observation"),
    (r"解法|方針|アルゴリズム|解き方|想定解", "solution"),
    (r"計算量", "complexity"),
    (r"実装|コード|解答例|回答例|ソースコード", "code"),
    (r"証明", "proof"),
]
_PSEUDO_HEADING_MAX = 25
# 実装例の見出しがなくても、この行数以上の <pre> はコードとみなす
_CODE_MIN_LINES = 8
_SENTENCE_END = re.compile(r"(?<=[。．！？\n])")


@dataclass(frozen=True)
class Chunk:
    text: str
    section: str
    heading: str
    chunk_index: int


@dataclass
class _Block:
    kind: str  # "heading" | "text" | "code" | "proof"
    text: str


def _classify_heading(text: str) -> str:
    for pattern, section in _SECTION_KEYWORDS:
        if re.match(rf"\s*[#■●◆・【\[(（]?\s*({pattern})", text):
            return section
    return "other"


def _inline_text(el: Tag | NavigableString) -> str:
    """インライン要素を連結し、ソース上の改行・連続空白を 1 つの空白にまとめる。"""
    if isinstance(el, NavigableString):
        return re.sub(r"\s+", " ", str(el)).strip()
    for br in el.find_all("br"):
        br.replace_with("\n")
    lines = el.get_text("").split("\n")
    return "\n".join(s for s in (re.sub(r"\s+", " ", line).strip() for line in lines) if s)


def _list_text(el: Tag) -> str:
    return "\n".join(f"- {_inline_text(li)}" for li in el.find_all("li", recursive=False))


def _is_pseudo_heading(el: Tag, text: str) -> bool:
    if not text or len(text) > _PSEUDO_HEADING_MAX or "\n" in text:
        return False
    # 「想定解は次の事実に注目しています。」のような文は見出しではない
    if text.endswith(("。", "．", "、")):
        return False
    if _classify_heading(text) != "other":
        return True
    # 段落全体が太字なら見出しとみなす
    strong = el.find(["strong", "b"])
    return strong is not None and strong.get_text(strip=True) == text


def _blocks(parent: Tag) -> list[_Block]:
    blocks: list[_Block] = []
    for el in parent.children:
        if isinstance(el, NavigableString):
            text = _inline_text(el)
            if text:
                blocks.append(_Block("text", text))
            continue
        if not isinstance(el, Tag):
            continue

        name = el.name
        if re.fullmatch(r"h[1-6]", name):
            blocks.append(_Block("heading", _inline_text(el)))
        elif name == "pre":
            blocks.append(_Block("code", el.get_text().strip("\n")))
        elif name == "details":
            summary = el.find("summary")
            label = summary.get_text(strip=True) if summary else ""
            if summary:
                summary.extract()
            if _classify_heading(label) == "proof":
                blocks.append(_Block("proof", _inline_text(el)))
            else:
                if label:
                    blocks.append(_Block("heading", label))
                blocks.extend(_blocks(el))
        elif name in ("ul", "ol"):
            items = el.find_all("li", recursive=False)
            if len(items) == 1 and _is_pseudo_heading(items[0], _inline_text(items[0])):
                blocks.append(_Block("heading", _inline_text(items[0])))
            else:
                text = _list_text(el)
                if text:
                    blocks.append(_Block("text", text))
        elif name in ("div", "section", "blockquote") and el.find(["p", "pre", "ul", "ol", "details", "h3", "h4"]):
            blocks.extend(_blocks(el))
        elif name in ("img", "script", "style", "hr"):
            continue
        else:
            text = _inline_text(el)
            if not text:
                continue
            kind = "heading" if name == "p" and _is_pseudo_heading(el, text) else "text"
            blocks.append(_Block(kind, text))
    return blocks


def _split_text(text: str, max_chars: int) -> list[str]:
    """文末で区切りながら max_chars 以下の断片に分ける。"""
    if len(text) <= max_chars:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in (s for s in _SENTENCE_END.split(text) if s):
        while len(sentence) > max_chars:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if len(current) + len(sentence) > max_chars:
            pieces.append(current)
            current = ""
        current += sentence
    if current:
        pieces.append(current)
    return [p.strip() for p in pieces if p.strip()]


def _sections(body_html: str) -> list[tuple[str, str, list[str]]]:
    """(section, heading, texts) の並びに変換する。"""
    soup = BeautifulSoup(body_html, "html.parser")
    sections: list[tuple[str, str, list[str]]] = []
    section, heading, texts = "body", "", []

    def flush():
        if texts:
            sections.append((section, heading, texts))

    for block in _blocks(soup):
        if block.kind == "heading":
            flush()
            section, heading, texts = _classify_heading(block.text), block.text, []
        elif block.kind == "proof":
            flush()
            sections.append(("proof", "証明", [block.text]))
            texts = []
        elif block.kind == "code":
            lines = block.text.count("\n") + 1
            if section == "code" or lines >= _CODE_MIN_LINES:
                flush()
                sections.append(("code", heading if section == "code" else "", [block.text]))
                texts = []
                if section == "code":
                    section, heading = "body", ""
            else:
                texts.append(block.text)  # 短い図などは本文の一部として扱う
        else:
            texts.append(block.text)
    flush()
    return sections


def chunk_editorial(body_html: str, max_chars: int = DEFAULT_MAX_CHARS) -> list[Chunk]:
    """解説本文 HTML をセクション付きのチャンクに分割する。"""
    chunks: list[Chunk] = []
    for section, heading, texts in _sections(body_html):
        if section == "code":
            # コードは分割せず 1 チャンクにする（埋め込み時は先頭のみ使われる）
            pieces = ["\n".join(texts)]
        else:
            pieces = []
            current = ""
            for text in texts:
                for piece in _split_text(text, max_chars):
                    if current and len(current) + 1 + len(piece) > max_chars:
                        pieces.append(current)
                        current = piece
                    else:
                        current = f"{current}\n{piece}" if current else piece
            if current:
                pieces.append(current)
        for piece in pieces:
            if piece.strip():
                chunks.append(Chunk(piece, section, heading, len(chunks)))
    return chunks


def extract_body_text(body_html: str) -> str:
    """コードと証明を除いた解説本文を 1 つの文字列にする。"""
    return "\n".join(
        "\n".join(texts)
        for section, _, texts in _sections(body_html)
        if section not in _NON_BODY_SECTIONS
    )


def get_problem_body_text(problem_id: str, base_dir: Path = EDITORIALS_DIR) -> str:
    """保存済みの公式解説（別解を除く）から、本問の解説本文だけを連結して返す。"""
    meta = load_meta(problem_id, base_dir)
    if meta is None:
        return ""
    pdir = problem_dir(problem_id, base_dir)
    parts = []
    for ed in meta.get("editorials", []):
        if ed.get("editorial_type") != "official":
            continue
        path = pdir / f"editorial_{ed['editorial_id']}.html"
        if not path.exists():
            continue
        body_html = parse_editorial_page(path.read_text(encoding="utf-8"))["body_html"]
        text = extract_body_text(body_html)
        if text:
            parts.append(text)
    return "\n\n".join(parts)
