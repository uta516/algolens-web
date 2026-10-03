"""コンテスト用フォルダ: ファイルの作成・場所からの問題の読み取り・c.txt の読み取り・
振り返りでのファイルの見つけ方・コンテスト中の利用を止める判定のテスト。"""

import os
import time
from pathlib import Path

import pytest

from app.services.contests import NOT_FINISHED_MESSAGE, UNKNOWN_MESSAGE, finished_error
from app.services.workspace import (
    create_contest_files,
    find_local_code,
    parse_sample_file,
    ref_from_path,
    sample_template,
)

# ---------------------------------------------------------------------------
# ファイルの作成（上書きしない・--upto）
# ---------------------------------------------------------------------------


def test_create_contest_files_defaults_to_a_through_d(tmp_path):
    results = create_contest_files(tmp_path, "abc477")

    names = sorted(p.name for p, _ in results)
    assert names == ["a.py", "a.txt", "b.py", "b.txt", "c.py", "c.txt", "d.py", "d.txt"]
    assert all(created for _, created in results)
    assert all(p.parent == tmp_path / "abc477" for p, _ in results)


def test_create_contest_files_upto_e(tmp_path):
    results = create_contest_files(tmp_path, "abc477", upto="e")
    assert sorted({p.stem for p, _ in results}) == ["a", "b", "c", "d", "e"]


def test_create_contest_files_contents(tmp_path):
    create_contest_files(tmp_path, "abc477")
    code = (tmp_path / "abc477" / "c.py").read_text(encoding="utf-8")
    assert "https://atcoder.jp/contests/abc477/tasks/abc477_c" in code
    assert "map(int, input().split())" in code
    assert all(line.startswith("#") for line in code.splitlines() if line.strip())  # コメントだけ

    sample = (tmp_path / "abc477" / "c.txt").read_text(encoding="utf-8")
    for i in (1, 2, 3):
        assert f"=== 入力{i} ===" in sample and f"=== 出力{i} ===" in sample


def test_create_contest_files_does_not_overwrite(tmp_path):
    folder = tmp_path / "abc477"
    folder.mkdir()
    (folder / "a.py").write_text("print('mine')\n", encoding="utf-8")
    (folder / "a.txt").write_text("my samples\n", encoding="utf-8")

    results = dict(create_contest_files(tmp_path, "abc477"))

    assert results[folder / "a.py"] is False
    assert results[folder / "a.txt"] is False
    assert results[folder / "b.py"] is True
    assert (folder / "a.py").read_text(encoding="utf-8") == "print('mine')\n"
    assert (folder / "a.txt").read_text(encoding="utf-8") == "my samples\n"


def test_create_contest_files_rejects_bad_input(tmp_path):
    with pytest.raises(ValueError):
        create_contest_files(tmp_path, "abc477", upto="ex")
    with pytest.raises(ValueError):
        create_contest_files(tmp_path, "../evil")


# ---------------------------------------------------------------------------
# ファイルの場所からの問題の読み取り
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("path", "contest", "letter", "task_id"),
    [
        ("submissions/abc477/c.py", "abc477", "c", "abc477_c"),
        ("submissions/abc477/c.txt", "abc477", "c", "abc477_c"),
        ("x/ABC477/E.py", "abc477", "e", "abc477_e"),
        ("submissions/abc001/c.py", "abc001", "c", "abc001_3"),   # 古い ABC は末尾が数字
        ("submissions/abc019/d.py", "abc019", "d", "abc019_4"),
        ("submissions/abc020/a.py", "abc020", "a", "abc020_a"),   # ABC020 から記号
    ],
)
def test_ref_from_path(path, contest, letter, task_id):
    ref = ref_from_path(Path(path))
    assert (ref.contest_id, ref.letter, ref.task_id) == (contest, letter, task_id)
    assert ref.url == f"https://atcoder.jp/contests/{contest}/tasks/{task_id}"


@pytest.mark.parametrize("path", ["submissions/abc477/notes.md", "submissions/abc477/main.py", "submissions/c.py"])
def test_ref_from_path_rejects_other_files(path):
    with pytest.raises(ValueError):
        ref_from_path(Path(path))


# ---------------------------------------------------------------------------
# c.txt の読み取り
# ---------------------------------------------------------------------------

def test_parse_sample_file_pairs_inputs_and_outputs():
    text = "=== 入力1 ===\n3\n1 2 3\n=== 出力1 ===\n6\n=== 入力2 ===\n1\n5\n=== 出力2 ===\n5\n"
    assert parse_sample_file(text) == [
        {"index": 1, "input": "3\n1 2 3\n", "output": "6\n"},
        {"index": 2, "input": "1\n5\n", "output": "5\n"},
    ]


def test_parse_sample_file_skips_empty_pairs():
    assert parse_sample_file(sample_template()) == []
    text = sample_template().replace("=== 入力2 ===\n", "=== 入力2 ===\n7\n").replace("=== 出力2 ===\n", "=== 出力2 ===\n49\n")
    assert parse_sample_file(text) == [{"index": 2, "input": "7\n", "output": "49\n"}]


def test_parse_sample_file_keeps_pair_without_output():
    text = "=== 入力1 ===\nabc\n=== 出力1 ===\n\n=== 入力2 ===\n=== 出力2 ===\n"
    assert parse_sample_file(text) == [{"index": 1, "input": "abc\n", "output": ""}]


def test_parse_sample_file_trims_blank_lines_and_crlf():
    text = "=== 入力1 ===\r\n\r\n4 5\r\n\r\n\r\n=== 出力1 ===\r\n  9\r\n\r\n"
    assert parse_sample_file(text) == [{"index": 1, "input": "4 5\n", "output": "  9\n"}]


def test_parse_sample_file_keeps_inner_blank_lines_and_ignores_text_before_headers():
    text = "メモ\n=== 入力1 ===\na\n\nb\n=== 出力1 ===\nok\n"
    assert parse_sample_file(text) == [{"index": 1, "input": "a\n\nb\n", "output": "ok\n"}]


def test_parse_sample_file_accepts_more_pairs_and_any_order():
    text = "=== 出力4 ===\n2\n=== 入力4 ===\n1\n=== 入力1 ===\n0\n=== 出力1 ===\n1\n"
    assert [c["index"] for c in parse_sample_file(text)] == [1, 4]


# ---------------------------------------------------------------------------
# 振り返りでのファイルの見つけ方
# ---------------------------------------------------------------------------

def _write(path: Path, text: str, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def test_find_local_code_uses_contest_folder(tmp_path):
    _write(tmp_path / "abc477" / "c.py", "print(3)\n")
    assert find_local_code(tmp_path, "abc477", "C", "abc477_c") == "print(3)\n"


def test_find_local_code_maps_old_contest_by_letter(tmp_path):
    _write(tmp_path / "abc001" / "c.py", "print('old')\n")
    assert find_local_code(tmp_path, "abc001", "C", "abc001_3") == "print('old')\n"


def test_find_local_code_falls_back_to_problem_id_in_name(tmp_path):
    _write(tmp_path / "misc" / "abc476_d_wa.py", "print('wa')\n")
    assert find_local_code(tmp_path, "abc476", "D", "abc476_d") == "print('wa')\n"


def test_find_local_code_prefers_contest_folder_over_name_match(tmp_path):
    _write(tmp_path / "abc476_d.py", "print('by name')\n", mtime=time.time() + 100)
    _write(tmp_path / "abc476" / "d.py", "print('folder')\n")
    assert find_local_code(tmp_path, "abc476", "D", "abc476_d") == "print('folder')\n"


def test_find_local_code_picks_newest_name_match(tmp_path):
    now = time.time()
    _write(tmp_path / "abc476_d_v1.py", "print(1)\n", mtime=now - 100)
    _write(tmp_path / "abc476_d_v2.py", "print(2)\n", mtime=now)
    assert find_local_code(tmp_path, "abc476", "D", "abc476_d") == "print(2)\n"


def test_find_local_code_ignores_template_only_file(tmp_path):
    create_contest_files(tmp_path, "abc477")  # コメントだけの c.py
    assert find_local_code(tmp_path, "abc477", "C", "abc477_c") is None


def test_find_local_code_does_not_match_longer_ids_or_sample_files(tmp_path):
    _write(tmp_path / "abc4760_d.py", "print('other contest')\n")
    _write(tmp_path / "abc476" / "d.txt", "=== 入力1 ===\n1\n")  # サンプルのファイルはコードではない
    assert find_local_code(tmp_path, "abc476", "D", "abc476_d") is None


def test_find_local_code_without_folder(tmp_path):
    assert find_local_code(None, "abc476", "D", "abc476_d") is None
    assert find_local_code(tmp_path / "missing", "abc476", "D", "abc476_d") is None


# ---------------------------------------------------------------------------
# コンテスト中の利用を止める判定
# ---------------------------------------------------------------------------

_CONTEST = {"id": "abc477", "start_epoch_second": 1_000_000, "duration_second": 6000}


def test_finished_error_blocks_before_start_and_during_contest():
    assert finished_error(_CONTEST, now=999_000) == NOT_FINISHED_MESSAGE
    assert finished_error(_CONTEST, now=1_000_000 + 5999) == NOT_FINISHED_MESSAGE


def test_finished_error_allows_after_end():
    assert finished_error(_CONTEST, now=1_000_000 + 6000) is None
    assert finished_error(_CONTEST, now=2_000_000) is None


def test_finished_error_blocks_unknown_contest():
    assert finished_error(None, now=2_000_000) == UNKNOWN_MESSAGE


def test_import_is_blocked_during_contest(client, monkeypatch):
    from app.routers import review

    monkeypatch.setattr(review, "find_contest", lambda cid: {**_CONTEST, "start_epoch_second": time.time() - 60})
    resp = client.post("/review/import", json={"username": "me", "contest_id": "abc477"})
    assert resp.status_code == 403
    assert "コンテスト終了後に使ってください" in resp.json()["detail"]


def test_explain_is_blocked_during_contest(client, monkeypatch):
    from app.routers import tutor
    from app.services.tutor import ProblemData

    monkeypatch.setattr(tutor, "load_problem", lambda pid: ProblemData(pid, "abc477", "C", "", []))
    monkeypatch.setattr(tutor, "find_contest", lambda cid: {**_CONTEST, "start_epoch_second": time.time() - 60})
    monkeypatch.setattr(tutor, "_gemini_client", lambda: pytest.fail("Gemini を呼んではいけない"))
    resp = client.post("/tutor/explain", json={"problem_id": "abc477_c", "code": "print(1)", "verdict": "WA"})
    assert resp.status_code == 403
    assert "コンテスト終了後に使ってください" in resp.json()["detail"]
