"""保存済みの公式解説（data/editorials）を解説ストアに登録する。"""

from pathlib import Path

from app.services.editorial_chunker import chunk_editorial
from app.services.editorial_scraper import EDITORIALS_DIR, load_meta, parse_editorial_page, problem_dir
from app.services.vector_store import EditorialVectorStore, build_records


def index_problem(store: EditorialVectorStore, problem_id: str, base_dir: Path = EDITORIALS_DIR) -> int:
    """問題の公式解説を分割・埋め込みして登録し直す。登録したチャンク数を返す（解説がなければ 0）。"""
    meta = load_meta(problem_id, base_dir)
    if meta is None or not meta["editorials"]:
        return 0
    records = []
    for ed in meta["editorials"]:
        path = problem_dir(problem_id, base_dir) / f"editorial_{ed['editorial_id']}.html"
        body_html = parse_editorial_page(path.read_text(encoding="utf-8"))["body_html"]
        records += build_records(meta, ed["editorial_id"], ed["editorial_type"], chunk_editorial(body_html))
    store.replace_problem(problem_id, records)
    return len(records)
