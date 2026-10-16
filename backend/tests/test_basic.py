"""Smoke tests: chunking, retrieval helpers, API startup (no Ollama needed for most)."""
from backend.app import ingest
from backend.app.retrieval import normalize_query, keywords, build_context


def test_chunk_short():
    assert ingest.chunk_page_text("hello world") == ["hello world"]
    assert ingest.chunk_page_text("") == []


def test_chunk_long_splits_with_overlap():
    txt = "Sentence one. " * 200
    parts = ingest.chunk_page_text(txt, chunk_chars=300, overlap=50)
    assert len(parts) > 2
    assert all(len(p) <= 340 for p in parts)


def test_normalize():
    assert normalize_query("  Hello   World ") == "Hello World"


def test_keywords():
    kws = keywords("What is normalization in databases?")
    assert "normalization" in kws or "databases" in kws


def test_build_context_truncates():
    chunks = [{"filename": "a.pdf", "page": 1, "heading": "", "text": "x" * 5000}]
    ctx = build_context(chunks, max_chars=1000)
    assert len(ctx) <= 1300


def test_api_imports():
    from backend.app.main import app
    routes = {r.path for r in app.routes}
    assert "/api/health" in routes
    assert "/api/chat" in routes
    assert "/api/documents/upload" in routes
