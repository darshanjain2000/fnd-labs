"""Chroma + local sentence-transformers embedder.

Heavy imports (`chromadb`, `sentence_transformers`) are deferred so the
FastAPI app can boot even when these extras are not yet installed in dev.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)


class RAGStore:
    def __init__(self, collection: str = "past_trades") -> None:
        self.settings = get_settings()
        self.collection_name = collection
        self._client: Any | None = None
        self._collection: Any | None = None
        self._embedder: Any | None = None

    def _lazy_init(self) -> bool:
        if self._collection is not None:
            return True
        try:
            import chromadb  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as e:
            log.warning("rag_deps_missing", error=str(e))
            return False

        self._client = chromadb.PersistentClient(path=self.settings.chroma_path)
        self._collection = self._client.get_or_create_collection(self.collection_name)
        self._embedder = SentenceTransformer("BAAI/bge-small-en-v1.5")
        return True

    def _embed(self, texts: list[str]) -> list[list[float]]:
        assert self._embedder is not None
        return [
            v.tolist() for v in self._embedder.encode(texts, normalize_embeddings=True)
        ]

    def add_trade(self, trade_id: int, text: str, metadata: dict | None = None) -> None:
        if not self._lazy_init():
            return
        assert self._collection is not None
        self._collection.add(
            ids=[f"trade-{trade_id}"],
            embeddings=self._embed([text]),
            documents=[text],
            metadatas=[metadata or {}],
        )

    def query_similar(self, text: str, k: int = 5) -> list[str]:
        if not self._lazy_init():
            return []
        assert self._collection is not None
        res = self._collection.query(query_embeddings=self._embed([text]), n_results=k)
        docs = res.get("documents", [[]])
        return docs[0] if docs else []
