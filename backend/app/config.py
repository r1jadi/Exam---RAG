"""Central configuration. All local-only, no cloud."""
from __future__ import annotations
import os
from pathlib import Path

# Project root = parent of backend/
ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("STUDY_DATA_DIR", str(ROOT / "data")))
PDF_DIR = DATA_DIR / "pdfs"
CHROMA_DIR = DATA_DIR / "chroma"
DB_PATH = DATA_DIR / "app.db"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
CHAT_MODEL = os.environ.get("STUDY_CHAT_MODEL", "qwen3.5:9b")
EMBED_MODEL = os.environ.get("STUDY_EMBED_MODEL", "qwen3-embedding:0.6b")
# Small-model fallback that fits easily in 16GB RAM / CPU
FALLBACK_CHAT_MODEL = os.environ.get("STUDY_FALLBACK_CHAT_MODEL", "qwen2.5:3b")

OLLAMA_NUM_CTX = int(os.environ.get("STUDY_NUM_CTX", "8192"))
RETRIEVAL_TOP_K = int(os.environ.get("STUDY_TOP_K", "6"))
CHUNK_CHARS = int(os.environ.get("STUDY_CHUNK_CHARS", "900"))
CHUNK_OVERLAP = int(os.environ.get("STUDY_CHUNK_OVERLAP", "150"))
MAX_CONTEXT_CHARS = int(os.environ.get("STUDY_MAX_CONTEXT_CHARS", "12000"))
GEN_MAX_TOKENS = int(os.environ.get("STUDY_GEN_MAX_TOKENS", "900"))
GEN_TEMPERATURE = float(os.environ.get("STUDY_TEMPERATURE", "0.2"))

FRONTEND_DEV_URL = "http://127.0.0.1:5173"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = int(os.environ.get("STUDY_BACKEND_PORT", "8000"))

ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
]


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
