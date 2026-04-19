"""RAG: local sentence-transformers embeddings + Chroma persistent store."""
from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.core.logging import get_logger

log = get_logger(__name__)

_EMBED_MODEL_NAME = "BAAI/bge-small-en-v1.5"


class RAGStore:
    def __init__(self) -> None:
        self.s = get_settings()
        self._client: Any = None
        self._collection: Any = None
        self._embedder: Any = None

    def _lazy_init(self) -> bool:
        if self._collection is not None:
            return True
        try:
            import chromadb  # type: ignore
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError:
            log.warning("rag_disabled_missing_deps")
            return False
        self._client = chromadb.PersistentClient(path=self.s.chroma_path)
        self._collection = self._client.get_or_create_collection("past_trades")
        self._embedder = SentenceTransformer(_EMBED_MODEL_NAME)
        return True

    def add(self, doc_id: str, text: str, metadata: dict) -> None:
        if not self._lazy_init():
            return
        emb = self._embedder.encode([text]).tolist()
        self._collection.add(ids=[doc_id], embeddings=emb, documents=[text], metadatas=[metadata])

    def query(self, text: str, k: int = 3) -> list[str]:
        if not self._lazy_init():
            return []
        emb = self._embedder.encode([text]).tolist()
        res = self._collection.query(query_embeddings=emb, n_results=k)
        docs = res.get("documents", [[]])[0]
        return list(docs)
