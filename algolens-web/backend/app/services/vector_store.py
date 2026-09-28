"""公式解説チャンクのベクトルストア（multilingual-e5-small + ChromaDB）。

タグは推測値で精度が低いため、メタデータとして保存するだけで検索の絞り込みには使わない。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence

from app.core.config import settings
from app.services.editorial_chunker import Chunk

E5_MODEL_NAME = "intfloat/multilingual-e5-small"
COLLECTION_NAME = "atcoder_editorials"
# メモリを使いすぎないよう、ベクトル化は 16 件ずつ行う
EMBED_BATCH_SIZE = 16
# 検索対象から外すセクション（コードと証明は考え方の類似度を下げるため）
DEFAULT_EXCLUDED_SECTIONS: tuple[str, ...] = ("code", "proof")
# 重複除去で問題数が減る分を見込んで、最初は k の何倍のチャンクを取るか
_OVERFETCH_FACTOR = 5
_DEFAULT_CHROMA_DIR =Path(__file__).resolve().parent.parent.parent / "data" / "chroma"


def resolve_chroma_dir() -> Path:
    """環境変数 CHROMA_DIR（settings.chroma_dir）があればそれを、なければ backend/data/chroma を返す。"""
    value = settings.chroma_dir.strip()
    return Path(value).expanduser() if value else _DEFAULT_CHROMA_DIR


class Embedder(Protocol):
    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class E5Embedder:
    """e5 系モデル用の埋め込み。保存文には "passage: "、検索文には "query: " を付ける。"""

    def __init__(self, model=None, model_name: str = E5_MODEL_NAME, batch_size: int = EMBED_BATCH_SIZE):
        if model is None:
            from sentence_transformers import SentenceTransformer

            model = SentenceTransformer(model_name, device="cpu")
        self._model = model
        self._batch_size = batch_size

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts, normalize_embeddings=True, batch_size=self._batch_size
        )
        return [list(map(float, v)) for v in vectors]

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        return self._encode([f"passage: {t}" for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([f"query: {text}"])[0]


@dataclass(frozen=True)
class ChunkRecord:
    id: str
    text: str
    metadata: dict


@dataclass(frozen=True)
class SearchResult:
    id: str
    text: str
    score: float  # コサイン類似度（1 - 距離）
    metadata: dict


def build_records(
    problem_meta: dict,
    editorial_id: int,
    editorial_type: str,
    chunks: list[Chunk],
) -> list[ChunkRecord]:
    """チャンクに problem_id, contest_id, difficulty, tags, section などを付けたレコードを作る。"""
    base = {
        "problem_id": problem_meta["problem_id"],
        "contest_id": problem_meta["contest_id"],
        "title": problem_meta.get("title", ""),
        "tags": problem_meta.get("tags") or "",
    }
    # ChromaDB のメタデータは None を持てないため、難易度不明なら項目ごと省く
    if problem_meta.get("difficulty") is not None:
        base["difficulty"] = float(problem_meta["difficulty"])

    return [
        ChunkRecord(
            id=f"{problem_meta['problem_id']}-{editorial_id}-{chunk.chunk_index}",
            text=chunk.text,
            metadata={
                **base,
                "section": chunk.section,
                "heading": chunk.heading,
                "editorial_id": editorial_id,
                "editorial_type": editorial_type,
                "chunk_index": chunk.chunk_index,
            },
        )
        for chunk in chunks
    ]


class EditorialVectorStore:
    def __init__(self, persist_dir: Path | None = None, embedder: Embedder | None = None):
        import chromadb

        path = Path(persist_dir) if persist_dir else resolve_chroma_dir()
        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path), settings=chromadb.Settings(anonymized_telemetry=False)
        )
        self._collection = self._client.get_or_create_collection(
            COLLECTION_NAME,
            configuration={"hnsw": {"space": "cosine"}},
            embedding_function=None,
        )
        self._embedder = embedder or E5Embedder()

    def count(self) -> int:
        return self._collection.count()

    def has_problem(self, problem_id: str) -> bool:
        found = self._collection.get(where={"problem_id": problem_id}, limit=1, include=[])
        return bool(found["ids"])

    def replace_problem(self, problem_id: str, records: list[ChunkRecord]) -> None:
        """問題のチャンクを入れ替える（再分割で減ったチャンクが残らないよう先に削除する）。"""
        self._collection.delete(where={"problem_id": problem_id})
        for start in range(0, len(records), EMBED_BATCH_SIZE):
            batch = records[start:start + EMBED_BATCH_SIZE]
            self._collection.add(
                ids=[r.id for r in batch],
                documents=[r.text for r in batch],
                metadatas=[r.metadata for r in batch],
                embeddings=self._embedder.embed_passages([r.text for r in batch]),
            )

    def search(
        self,
        text: str,
        k: int = 10,
        exclude_sections: Sequence[str] = DEFAULT_EXCLUDED_SECTIONS,
        exclude_problem_ids: Sequence[str] = (),
    ) -> list[SearchResult]:
        """文章に似た解説を、1 問につき最も近いチャンク 1 件ずつ、上位 k 問分返す。"""
        total = self.count()
        if total == 0 or k <= 0:
            return []
        query_embedding = self._embedder.embed_query(text)
        where = _build_where(exclude_sections, exclude_problem_ids)

        # 同じ問題のチャンクが上位を占めることがあるため、k 問そろうまで取得件数を増やす
        n = min(k * _OVERFETCH_FACTOR, total)
        while True:
            res = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=n,
                where=where,
                include=["documents", "metadatas", "distances"],
            )
            results = _best_per_problem(res, k)
            if len(results) >= k or len(res["ids"][0]) < n or n >= total:
                return results
            n = min(n * 2, total)


def _build_where(exclude_sections: Sequence[str], exclude_problem_ids: Sequence[str]) -> dict | None:
    conditions = []
    if exclude_sections:
        conditions.append({"section": {"$nin": list(exclude_sections)}})
    if exclude_problem_ids:
        conditions.append({"problem_id": {"$nin": list(exclude_problem_ids)}})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def _best_per_problem(res: dict, k: int) -> list[SearchResult]:
    """距離の近い順に並んだ結果から、問題ごとに先頭の 1 件だけを残して k 件返す。"""
    results: list[SearchResult] = []
    seen: set[str] = set()
    for i, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        if meta["problem_id"] in seen:
            continue
        seen.add(meta["problem_id"])
        results.append(SearchResult(id=i, text=doc, score=1.0 - dist, metadata=meta))
        if len(results) == k:
            break
    return results
