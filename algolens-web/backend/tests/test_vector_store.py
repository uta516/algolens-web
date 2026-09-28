"""vector_store のテスト（e5 モデルはダウンロードせず、偽の埋め込みを使う）。"""

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.editorial_chunker import Chunk
from app.services.vector_store import (
    E5Embedder,
    EditorialVectorStore,
    build_records,
    resolve_chroma_dir,
)

_BACKEND_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 保存先の解決
# ---------------------------------------------------------------------------

def test_resolve_chroma_dir_defaults_to_backend_data(monkeypatch):
    monkeypatch.setattr(settings, "chroma_dir", "")
    assert resolve_chroma_dir() == _BACKEND_DIR / "data" / "chroma"


def test_resolve_chroma_dir_uses_setting(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "vec"))
    assert resolve_chroma_dir() == tmp_path / "vec"


# ---------------------------------------------------------------------------
# e5 の接頭辞
# ---------------------------------------------------------------------------

class _RecordingModel:
    def __init__(self):
        self.calls: list[list[str]] = []
        self.batch_sizes: list[int] = []

    def encode(self, texts, normalize_embeddings=False, batch_size=32, **kwargs):
        assert normalize_embeddings is True
        self.calls.append(list(texts))
        self.batch_sizes.append(batch_size)
        return [[1.0, 0.0] for _ in texts]


def test_e5_embedder_adds_passage_and_query_prefixes():
    model = _RecordingModel()
    embedder = E5Embedder(model=model)

    embedder.embed_passages(["本文A", "本文B"])
    embedder.embed_query("質問")

    assert model.calls == [["passage: 本文A", "passage: 本文B"], ["query: 質問"]]


def test_e5_embedder_encodes_16_at_a_time_by_default():
    model = _RecordingModel()
    E5Embedder(model=model).embed_passages(["x"] * 3)
    assert model.batch_sizes == [16]


# ---------------------------------------------------------------------------
# ChromaDB への保存と検索
# ---------------------------------------------------------------------------

_VOCAB = ["二分探索", "累積和", "グラフ", "オーバーフロー", "全探索"]


class _KeywordEmbedder:
    """語彙の出現で決まる決定的なベクトルを返す偽の埋め込み。"""

    def _vec(self, text: str) -> list[float]:
        v = [1.0 if w in text else 0.0 for w in _VOCAB]
        return v + [0.01]  # ゼロベクトルを避ける

    def embed_passages(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


_META = {
    "problem_id": "abc300_c",
    "contest_id": "abc300",
    "title": "C. Sample",
    "difficulty": -120.5,
    "tags": "全探索,実装",
}


def _records(problem_id: str, texts: list[str], meta=None, section: str = "body"):
    meta = dict(meta or _META, problem_id=problem_id)
    chunks = [Chunk(text=t, section=section, heading="", chunk_index=i) for i, t in enumerate(texts)]
    return build_records(meta, editorial_id=1001, editorial_type="official", chunks=chunks)


def test_build_records_attaches_metadata():
    records = _records("abc300_c", ["二分探索で解く"])
    assert records[0].id == "abc300_c-1001-0"
    assert records[0].metadata == {
        "problem_id": "abc300_c",
        "contest_id": "abc300",
        "title": "C. Sample",
        "difficulty": -120.5,
        "tags": "全探索,実装",
        "section": "body",
        "heading": "",
        "editorial_id": 1001,
        "editorial_type": "official",
        "chunk_index": 0,
    }


def test_build_records_handles_missing_difficulty():
    records = _records("abc300_c", ["x"], meta=dict(_META, difficulty=None))
    assert "difficulty" not in records[0].metadata


@pytest.fixture
def store(tmp_path):
    return EditorialVectorStore(tmp_path / "chroma", embedder=_KeywordEmbedder())


def test_search_returns_most_similar_chunk_first(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索で境界を求める", "グラフを作る"]))
    store.replace_problem("abc301_c", _records("abc301_c", ["累積和で区間和を求める"]))

    results = store.search("累積和を使う問題", k=10)

    assert len(results) == 2  # abc300_c のチャンクは 1 件にまとめられる
    top = results[0]
    assert top.text == "累積和で区間和を求める"
    assert top.metadata["problem_id"] == "abc301_c"
    assert top.metadata["section"] == "body"
    assert top.score > results[1].score


class _CountingEmbedder(_KeywordEmbedder):
    def __init__(self):
        self.passage_call_sizes: list[int] = []

    def embed_passages(self, texts):
        self.passage_call_sizes.append(len(texts))
        return super().embed_passages(texts)


def test_replace_problem_embeds_at_most_16_records_per_call(tmp_path):
    embedder = _CountingEmbedder()
    store = EditorialVectorStore(tmp_path / "chroma", embedder=embedder)

    store.replace_problem("abc300_c", _records("abc300_c", [f"全探索 {i}" for i in range(40)]))

    assert embedder.passage_call_sizes == [16, 16, 8]
    assert store.count() == 40


def test_search_limits_to_k(store):
    for i in range(15):
        store.replace_problem(f"abc{300 + i}_c", _records(f"abc{300 + i}_c", [f"全探索 {i}"]))
    assert len(store.search("全探索", k=10)) == 10


def test_replace_problem_removes_stale_chunks(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索 1", "二分探索 2", "二分探索 3"]))
    store.replace_problem("abc300_c", _records("abc300_c", ["グラフ 1"]))

    assert store.count() == 1
    assert store.has_problem("abc300_c")
    assert not store.has_problem("abc301_c")


def test_search_on_empty_store_returns_empty(store):
    assert store.search("なんでも") == []


def test_store_persists_across_instances(tmp_path):
    path = tmp_path / "chroma"
    EditorialVectorStore(path, embedder=_KeywordEmbedder()).replace_problem(
        "abc300_c", _records("abc300_c", ["オーバーフローに注意"])
    )
    reopened = EditorialVectorStore(path, embedder=_KeywordEmbedder())
    assert reopened.search("オーバーフロー", k=1)[0].metadata["problem_id"] == "abc300_c"


# ---------------------------------------------------------------------------
# 検索の絞り込み（section の除外・問題ごとの重複除去・問題の除外）
# ---------------------------------------------------------------------------

def test_search_excludes_code_and_proof_sections_by_default(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索のコード"], section="code"))
    store.replace_problem("abc301_c", _records("abc301_c", ["二分探索の証明"], section="proof"))
    store.replace_problem("abc302_c", _records("abc302_c", ["二分探索 グラフ"], section="solution"))

    results = store.search("二分探索", k=10)

    assert [r.metadata["problem_id"] for r in results] == ["abc302_c"]


def test_search_can_include_all_sections(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索のコード"], section="code"))
    assert len(store.search("二分探索", k=10, exclude_sections=())) == 1


def test_search_keeps_only_best_chunk_per_problem(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索 グラフ 累積和", "二分探索", "二分探索 全探索"]))
    store.replace_problem("abc301_c", _records("abc301_c", ["累積和"]))

    results = store.search("二分探索", k=10)

    assert [r.metadata["problem_id"] for r in results] == ["abc300_c", "abc301_c"]
    assert results[0].text == "二分探索"


def test_search_returns_k_distinct_problems_after_dedup(store):
    # 1 問あたりのチャンクが多く、上位 k チャンクが同じ問題で埋まっても k 問返す
    for i in range(5):
        pid = f"abc{300 + i}_c"
        store.replace_problem(pid, _records(pid, [f"二分探索 {j}" for j in range(20)]))
    store.replace_problem("abc399_c", _records("abc399_c", ["累積和"]))

    results = store.search("二分探索", k=6)

    ids = [r.metadata["problem_id"] for r in results]
    assert len(ids) == 6
    assert len(set(ids)) == 6
    assert ids[-1] == "abc399_c"


def test_search_excludes_given_problem_ids(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索"]))
    store.replace_problem("abc301_c", _records("abc301_c", ["二分探索 累積和"]))

    results = store.search("二分探索", k=10, exclude_problem_ids=["abc300_c"])

    assert [r.metadata["problem_id"] for r in results] == ["abc301_c"]


def test_search_returns_empty_when_everything_is_filtered(store):
    store.replace_problem("abc300_c", _records("abc300_c", ["二分探索"], section="code"))
    assert store.search("二分探索", k=10) == []
