# Study Assistant — Fully Local AI Tutor (RAG)

Study your own lecture PDFs with a private AI that runs **entirely on your PC**.
No accounts, no cloud AI, no uploads. Built for **16 GB RAM, CPU-friendly**.

- **Chat models (Ollama, local):** `qwen3.5:9b` (main), fallback `qwen2.5:3b`
- **Embeddings (local):** `qwen3-embedding:0.6b`
- **Storage (local):** ChromaDB vectors + SQLite (`data/`), original PDFs kept in `data/pdfs/`
- Ask in **Albanian or English**, get answers with **[file.pdf, page N]** citations that open the PDF at that page.

## Start with 2 steps (Windows)

1. **First time only:** right-click `setup.ps1` → *Run with PowerShell*
   (installs Python/Node deps, pulls Ollama models, builds the app, runs checks).
2. **Every day:** double-click **`start_app.bat`** → the app opens in your browser.

| Address | What |
|---|---|
| http://127.0.0.1:8000 | App (when frontend built) + API docs at `/docs` |
| http://127.0.0.1:5173 | App (dev mode, if `frontend/dist` missing) |

If Ollama or a model is missing, the app shows a **setup screen** with the exact command
(`ollama pull qwen3.5:9b`, `ollama pull qwen3-embedding:0.6b`) instead of crashing.
It never sends your data to any cloud API.

## What you can do

1. **My Lectures** — drag & drop PDFs, auto page-by-page indexing, duplicate detection (file hash), re-index/delete, unreadable-page warnings (scanned pages need Tesseract OCR — the app tells you which pages).
2. **AI Tutor** — streaming chat, conversation history, filter to one lecture or all, Albanian/English, copy button, every answer cites real chunks; sources panel shows excerpts + opens PDF at the page.
3. **Summaries** — one lecture, or a topic across lectures. Coverage is stated honestly.
4. **Flashcards** — generate Q/A, reveal, mark Known/Hard, saved locally.
5. **Exam Practice** — MCQ + open questions, difficulty + count, hide-until-answer, auto-grading with explanations + sources.
6. **Mock exam** — timed, navigable, final score, attempts saved.
7. **Settings** — switch model (e.g. smaller one if RAM is tight), top-K, context size.

## If something goes wrong

- `Ollama is not running` → run `ollama serve` in a terminal, or re-run `start_app.bat`.
- `Model not found` → `ollama pull qwen3.5:9b` and `ollama pull qwen3-embedding:0.6b`.
- `Out of memory with 9b` → `ollama pull qwen2.5:3b`, then pick it in Settings → Save. Your PDFs/chats are kept.
- `Backend unreachable` → make sure the black "StudyAssistant-Backend" window is open; or run manually:
  `py -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`
- Scanned PDF pages with no text → install Tesseract (https://github.com/UB-Mannheim/tesseract/wiki), restart; otherwise those pages are listed, never silently indexed as empty.

## Verified on this machine (16 Oct 2026, Windows 11, 16 GB RAM)

- `py -m pytest backend/tests/test_basic.py -q` → **6 passed**
- Synthetic 3-page PDF → indexed **3 pages / 3 chunks**, retrieval found the right page with correct `[file, page N]` metadata
- Real local answer generation with `qwen3.5:9b` + `qwen3-embedding:0.6b` → grounded answer with citations (thinking mode disabled by default via `think:false` so answers aren't empty; set `STUDY_ENABLE_THINK=1` to re-enable reasoning traces)
- Flashcards: generated 3/3 · Exam: generated 2 questions, submit + grading + persistence OK
- Backend boot + `/api/health` + `/api/system/status` (both models detected) + built frontend served at `/` → OK
- `ollama list` confirmed: `qwen3.5:9b`, `qwen3-embedding:0.6b`, `qwen2.5:3b` (fallback)
- Local-only audit: no cloud AI/DB SDKs, no telemetry (Chroma telemetry explicitly off), only localhost + an ollama.com download hint string.

## For developers

```
backend/   FastAPI + PyMuPDF + ChromaDB + SQLite + Ollama client
frontend/  React + TS + Vite (no external fonts/scripts at runtime)
data/      pdfs/ chroma/ app.db  (created on first run, git-ignored)
```

- Backend tests: `py -m pytest backend/tests -q`
- Frontend build: `cd frontend && npm install && npm run build`
- Env overrides: copy `.env.example` to `.env`.

Implementation notes: chunking is page-aware (≈900 chars, 150 overlap, dedup by `(doc,page,chunk)`);
retrieval is hybrid (Chroma cosine + SQLite keyword) with weighted rerank, default top-K=6;
generation is grounded with mandatory citations and an explicit "not in lectures" fallback;
context is capped (~12k chars, 8192-token Ollama `num_ctx`) so 16 GB RAM / CPU works.
