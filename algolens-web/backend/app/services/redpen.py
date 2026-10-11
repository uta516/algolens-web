"""赤ペン: 元のコードへの変更の一覧（行番号・元の行・新しい行・理由）と、その適用。

LLM には修正後のコード全体ではなく変更の一覧を出させ、こちらで元のコードに当てる。
変更しない行（コメント・空行を含む）は元のまま残るので、全体の書き直しが起きない。
変更は replace（置き換え）・delete（削除）・insert_after（行の後ろに差し込み）の 3 種類。
"""

from dataclasses import dataclass, replace

ACTIONS = ("replace", "delete", "insert_after")
LINE_SLACK = 2  # original が指定の行と合わないとき、前後この行数以内で探す


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


def find_original_line(lines: list[str], line: int, original: str) -> int | None:
    """original が実際にある行番号。

    line の行と一致すればそのまま。合わなければ前後 LINE_SLACK 行以内で一致する行を探し、
    ちょうど 1 行だけならその行とみなす（LLM の行番号のずれを吸収する）。
    0 行・2 行以上なら None。一致は前後の空白を除いて比べる。
    """
    target = original.strip()
    if 1 <= line <= len(lines) and lines[line - 1].strip() == target:
        return line
    near = [
        i for i in range(max(1, line - LINE_SLACK), min(len(lines), line + LINE_SLACK) + 1)
        if i != line and lines[i - 1].strip() == target
    ]
    return near[0] if len(near) == 1 else None


def resolve_edits(code: str, edits: list[Edit]) -> list[Edit]:
    """変更の一覧を元のコードと照らし合わせ、行番号を直した一覧を返す。合わなければ EditError。

    合わない変更はまとめて 1 つの EditError にする（LLM に 1 度で全部直してもらうため）。
    空行は replace で書き込める（その位置への差し込みになる）。コメントの行は変えられない。
    何も変えない replace は一覧から外す。
    """
    lines = split_lines(code)
    n = len(lines)
    touched: set[int] = set()
    resolved: list[Edit] = []
    errors: list[str] = []
    for e in edits:
        if e.action == "insert_after":
            if not 0 <= e.line <= n:
                errors.append(f"insert_after の line {e.line} が範囲外です（元のコードは {n} 行）。")
                continue
            resolved.append(e)
            continue
        line = find_original_line(lines, e.line, e.original)
        if line is None:
            if not 1 <= e.line <= n:
                errors.append(f"{e.action} の line {e.line} が範囲外です（元のコードは {n} 行）。")
            else:
                errors.append(
                    f"line {e.line} の original が元のコードと合いません。"
                    f"元のコードの {e.line} 行目は {lines[e.line - 1].strip()!r} です（行番号を確かめてください）。"
                )
            continue
        if line in touched:
            errors.append(f"line {line} を 2 回以上 replace / delete しています。1 つにまとめてください。")
            continue
        actual = lines[line - 1]
        if actual.strip().startswith("#"):
            errors.append(
                f"line {line} はコメントの行です（{actual.strip()!r}）。コメントは変えずに残してください。"
                "コメントに書かれたコードを使いたいときは、insert_after で新しい行として入れてください。"
            )
            continue
        if e.action == "replace" and e.new.rstrip() == actual.rstrip():
            continue  # 何も変えない replace は無視する
        touched.add(line)
        resolved.append(replace(e, line=line))
    if errors:
        raise EditError("\n".join(f"- {msg}" for msg in errors) if len(errors) > 1 else errors[0])
    return resolved


def apply_edits(code: str, edits: list[Edit]) -> str:
    """元のコードに変更を当てる（resolve_edits で行番号を確かめてから）。合わなければ EditError。"""
    lines = split_lines(code)
    replaced: dict[int, list[str]] = {}
    deleted: set[int] = set()
    inserted: dict[int, list[str]] = {}
    for e in resolve_edits(code, edits):
        if e.action == "insert_after":
            inserted.setdefault(e.line, []).extend(e.new.split("\n"))
        elif e.action == "replace":
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
