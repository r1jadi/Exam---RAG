"""ChromaDB persistent vector store (local)."""
from __future__ import annotations
from typing import Optional

import chromadb
from chromadb.config import Settings

from . import config

_client = None
_collection = None


def get_client():
    global _client
    if _client is None:
        config.ensure_dirs()
        _client = chromadb.PersistentClient(
            path=str(config.CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
    return _client


def get_collection():
    global _collection
    if _collection is None:
        client = get_client()
        _collection = client.get_or_create_collection(
            name="lecture_chunks",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def count() -> int:
    try:
        return get_collection().count()
    except Exception:
        return 0


def delete_by_doc(doc_id: str) -> None:
    col = get_collection()
    try:
        col.delete(where={"doc_id": doc_id})
    except Exception:
        pass
