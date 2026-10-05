"""赤ペン: 元のコードへの変更の一覧（行番号・元の行・新しい行・理由）と、その適用。

LLM には修正後のコード全体ではなく変更の一覧を出させ、こちらで元のコードに当てる。
変更しない行（コメント・空行を含む）は元のまま残るので、全体の書き直しが起きない。
"""

from dataclasses import dataclass

ACTIONS = ("replace", "delete", "insert_after")


class EditError(ValueError):
    """変更の一覧が元のコードと合わないとき。メッセージはそのまま LLM へのやり直しの依頼に使う。"""


@dataclass(frozen=True)
class Edit:
    line: int        # 元のコードの行番号（insert_after の 0 は先頭）
    action: str      # replace / delete / insert_after
    original: str    # 元の行（insert_after は空）
    new: str         # 新しい行（複数行なら改行区切り。delete は空）
    reason: str


def split_lines(code: str) -> list[str]:
    """行番号を付けるときと同じ分け方（改行コードをそろえ、末尾の空行は除く）。"""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and lines[-1] == "":
        lines.pop()
    return lines


def parse_edits(raw) -> list[Edit]:
    """LLM の edits を Edit の一覧にする。形が違えば EditError。"""
    if not isinstance(raw, list) or not raw:
        raise EditError("edits が空か、一覧になっていませんでした。直す行を 1 つ以上挙げてください。")
    edits = []
    for i, item in enumerate(raw, 1):
        if not isinstance(item, dict):
            raise EditError(f"edits の {i} 個目が項目の形になっていませんでした。")
        action = item.get("action")
        line = item.get("line")
        if action not in ACTIONS:
            raise EditError(f"edits の {i} 個目の action が {action!r} でした。{' / '.join(ACTIONS)} のどれかにしてください。")
        if isinstance(line, float) and line.is_integer():
            line = int(line)
        if not isinstance(line, int) or isinstance(line, bool):
            raise EditError(f"edits の {i} 個目の line が整数ではありませんでした。")
        edits.append(Edit(
            line=line,
            action=action,
            original=str(item.get("original") or ""),
            new=str(item.get("new") or "").replace("\r\n", "\n"),
            reason=str(item.get("reason") or "").strip(),
        ))
    return edits


def apply_edits(code: str, edits: list[Edit]) -> str:
    """元のコードに変更を当てる。行番号・元の行が合わなければ EditError。"""
    lines = split_lines(code)
    n = len(lines)
    replaced: dict[int, list[str]] = {}
    deleted: set[int] = set()
    inserted: dict[int, list[str]] = {}
    for e in edits:
        if e.action == "insert_after":
            if not 0 <= e.line <= n:
                raise EditError(f"insert_after の line {e.line} が範囲外です（元のコードは {n} 行）。")
            inserted.setdefault(e.line, []).extend(e.new.split("\n"))
            continue
        if not 1 <= e.line <= n:
            raise EditError(f"{e.action} の line {e.line} が範囲外です（元のコードは {n} 行）。")
        if e.line in replaced or e.line in deleted:
            raise EditError(f"line {e.line} を 2 回以上 replace / delete しています。1 つにまとめてください。")
        actual = lines[e.line - 1]
        if not actual.strip() or actual.strip().startswith("#"):
            raise EditError(
                f"line {e.line} は空行かコメントの行です。空行とコメントは変えずに残し、"
                "新しい行は insert_after で入れてください。"
            )
        if e.original.strip() != actual.strip():
            raise EditError(
                f"line {e.line} の original が元のコードと合いません。"
                f"元のコードの {e.line} 行目は {actual.strip()!r} です（行番号を確かめてください）。"
            )
        if e.action == "replace" and e.new.rstrip() == actual.rstrip():
            continue  # 何も変えない replace は無視する
        if e.action == "replace":
            replaced[e.line] = e.new.split("\n")
        else:
            deleted.add(e.line)

    out = list(inserted.get(0, []))
    for i, line in enumerate(lines, 1):
        if i in replaced:
            out.extend(replaced[i])
        elif i not in deleted:
            out.append(line)
        out.extend(inserted.get(i, []))
    return "\n".join(out) + "\n"


def format_edits(edits: list[Edit]) -> str:
    """やり直しの依頼で前回の赤ペンを見せるための文字列。"""
    rows = []
    for e in edits:
        if e.action == "insert_after":
            rows.append(f"- {e.line} 行目の後に追加: {e.new!r}（{e.reason}）")
        elif e.action == "delete":
            rows.append(f"- {e.line} 行目を削除: {e.original!r}（{e.reason}）")
        else:
            rows.append(f"- {e.line} 行目: {e.original!r} → {e.new!r}（{e.reason}）")
    return "\n".join(rows)
