"""FastAPI backend — localhost only. Serves API + frontend dist."""
from __future__ import annotations
import asyncio
import io
import json
import os
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, db, ingest, retrieval, prompts, vectorstore
from . import ollama_client

config.ensure_dirs()
db.init_db()

app = FastAPI(title="Study Assistant (local RAG)", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- helpers ----------------

def model_or_fallback(requested: Optional[str]) -> str:
    return requested or config.CHAT_MODEL


async def ensure_chat_model(model: str) -> tuple[bool, str]:
    ok = await ollama_client.is_available()
    if not ok:
        return False, "Ollama is not running. Start Ollama (ollama serve) and try again."
    has = await ollama_client.has_model(model)
    if has:
        return True, ""
    alt = config.FALLBACK_CHAT_MODEL
    has_alt = await ollama_client.has_model(alt)
    msg = f"Model '{model}' not found locally. Run: ollama pull {model}"
    if has_alt:
        msg += f". Fallback available: {alt} (select it in Settings)."
    return False, msg


def sse_wrap(text: str) -> str:
    return f"data: {json.dumps({'delta': text})}\n\n"


# ---------------- system ----------------

@app.get("/api/health")
async def health():
    return {"ok": True, "app": "study-assistant-local", "time": time.time()}


@app.get("/api/system/status")
async def system_status():
    ollama = await ollama_client.is_available()
    models = await ollama_client.list_models() if ollama else []
    chat_ok = config.CHAT_MODEL in models or any(m.startswith(config.CHAT_MODEL) for m in models)
    embed_ok = config.EMBED_MODEL in models or any(m.startswith(config.EMBED_MODEL) for m in models)
    stats = db.dashboard_stats()
    import shutil
    total, used, free = shutil.disk_usage(str(config.DATA_DIR))
    # RAM info (best effort)
    ram_gb = None
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        ms = MS(); ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        ram_gb = round(ms.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        pass
    return {
        "ollama_available": ollama,
        "ollama_host": config.OLLAMA_HOST,
        "models_installed": models,
        "chat_model": config.CHAT_MODEL,
        "chat_model_ready": chat_ok,
        "embed_model": config.EMBED_MODEL,
        "embed_model_ready": embed_ok,
        "fallback_model": config.FALLBACK_CHAT_MODEL,
        "num_ctx": config.OLLAMA_NUM_CTX,
        "top_k": config.RETRIEVAL_TOP_K,
        "vector_count": vectorstore.count(),
        "ram_gb": ram_gb,
        "disk_free_gb": round(free / (1024 ** 3), 1),
        "stats": stats,
        "setup_help": None if (ollama and chat_ok and embed_ok) else setup_help_text(ollama, chat_ok, embed_ok),
    }


def setup_help_text(ollama: bool, chat_ok: bool, embed_ok: bool) -> str:
    lines = []
    if not ollama:
        lines.append("1) Install Ollama from https://ollama.com/download and run 'ollama serve'.")
    if not chat_ok:
        lines.append(f"2) Download chat model: ollama pull {config.CHAT_MODEL} (needs ~6GB free; 16GB RAM OK).")
    if not embed_ok:
        lines.append(f"3) Download embedding model: ollama pull {config.EMBED_MODEL}.")
    lines.append("Then restart this app. Your PDFs and chats are kept.")
    return "\n".join(lines)


class ConfigUpdate(BaseModel):
    chat_model: Optional[str] = None
    top_k: Optional[int] = None
    num_ctx: Optional[int] = None
    max_tokens: Optional[int] = None


@app.post("/api/system/config")
async def update_config(body: ConfigUpdate):
    if body.chat_model:
        config.CHAT_MODEL = body.chat_model
        os.environ["STUDY_CHAT_MODEL"] = body.chat_model
    if body.top_k:
        config.RETRIEVAL_TOP_K = max(1, min(12, body.top_k))
    if body.num_ctx:
        config.OLLAMA_NUM_CTX = max(2048, min(32768, body.num_ctx))
    if body.max_tokens:
        config.GEN_MAX_TOKENS = max(100, min(4000, body.max_tokens))
    return {"chat_model": config.CHAT_MODEL, "top_k": config.RETRIEVAL_TOP_K, "num_ctx": config.OLLAMA_NUM_CTX, "max_tokens": config.GEN_MAX_TOKENS}


@app.get("/api/dashboard")
async def dashboard():
    stats = db.dashboard_stats()
    s = await system_status()
    return {**stats, "system": {"ollama": s["ollama_available"], "chat_ready": s["chat_model_ready"], "embed_ready": s["embed_model_ready"]}}


# ---------------- documents ----------------

@app.get("/api/documents")
async def list_docs():
    docs = db.list_documents()
    import json as _j
    for d in docs:
        try:
            d["unreadable_pages"] = _j.loads(d.get("unreadable_pages") or "[]")
        except Exception:
            d["unreadable_pages"] = []
    return {"documents": docs, "vector_count": vectorstore.count()}


@app.post("/api/documents/upload")
async def upload(files: list[UploadFile] = File(...)):
    results = []
    for f in files:
        fname = f.filename or "unnamed.pdf"
        if not fname.lower().endswith(".pdf"):
            results.append({"filename": fname, "error": "Only PDF files are supported."})
            continue
        data = await f.read()
        if len(data) == 0:
            results.append({"filename": fname, "error": "Empty file."})
            continue
        if len(data) > 300 * 1024 * 1024:
            results.append({"filename": fname, "error": "File too large (>300MB)."})
            continue
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(data)
            tmp_path = Path(tmp.name)
        try:
            reg = ingest.register_document(fname, tmp_path, len(data))
        finally:
            try:
                tmp_path.unlink()
            except Exception:
                pass
        if reg["duplicate"]:
            results.append({"filename": fname, "duplicate": True, "document": reg["document"]})
        else:
            doc = reg["document"]
            # index in background-ish (await but sequential to bound RAM)
            try:
                info = await ingest.index_document(doc["id"])
                results.append({"filename": fname, "duplicate": False, "document_id": doc["id"], **info})
            except Exception as e:
                results.append({"filename": fname, "document_id": doc["id"], "error": str(e)[:1000]})
    return {"results": results}


@app.post("/api/documents/{doc_id}/reindex")
async def reindex(doc_id: str):
    try:
        info = await ingest.index_document(doc_id)
        return {"ok": True, **info}
    except Exception as e:
        raise HTTPException(500, str(e)[:1500])


@app.delete("/api/documents/{doc_id}")
async def delete_doc(doc_id: str):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "not found")
        d = dict(row)
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        conn.commit()
    finally:
        conn.close()
    vectorstore.delete_by_doc(doc_id)
    try:
        p = Path(d["file_path"])
        if p.exists():
            p.unlink()
    except Exception:
        pass
    return {"ok": True}


@app.get("/api/documents/{doc_id}/file")
async def serve_pdf(doc_id: str):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        if not row:
            raise HTTPException(404, "not found")
        d = dict(row)
    finally:
        conn.close()
    p = Path(d["file_path"])
    if not p.exists():
        raise HTTPException(404, "PDF file missing on disk")
    return FileResponse(str(p), media_type="application/pdf", filename=d["filename"])


@app.get("/api/search")
async def search(q: str, top_k: int = 6, doc_id: Optional[str] = None, filename: Optional[str] = None):
    ok = await ollama_client.is_available()
    if not ok:
        raise HTTPException(503, "Ollama not running")
    doc_ids = [doc_id] if doc_id else None
    chunks, nq = await retrieval.retrieve(q, top_k=top_k, doc_ids=doc_ids, filename=filename)
    return {"query": nq, "chunks": retrieval.format_citations(chunks), "raw": chunks}


# ---------------- chat ----------------

class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    doc_ids: Optional[list[str]] = None
    filename: Optional[str] = None
    language: str = "auto"
    model: Optional[str] = None
    top_k: Optional[int] = None


@app.get("/api/conversations")
async def list_convs():
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT 100").fetchall()
        return {"conversations": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/api/conversations")
async def new_conv():
    cid = uuid.uuid4().hex[:12]
    conn = db.connect()
    try:
        conn.execute("INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?,?,?,?)", (cid, "New chat", time.time(), time.time()))
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "title": "New chat"}


@app.delete("/api/conversations/{cid}")
async def del_conv(cid: str):
    conn = db.connect()
    try:
        conn.execute("DELETE FROM messages WHERE conv_id=?", (cid,))
        conn.execute("DELETE FROM conversations WHERE id=?", (cid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.get("/api/conversations/{cid}/messages")
async def get_messages(cid: str):
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM messages WHERE conv_id=? ORDER BY created_at ASC", (cid,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["citations"] = json.loads(d.get("citations") or "[]")
            except Exception:
                d["citations"] = []
            out.append(d)
        return {"messages": out}
    finally:
        conn.close()


def save_message(conv_id: str, role: str, content: str, citations: list) -> str:
    mid = uuid.uuid4().hex[:12]
    conn = db.connect()
    try:
        conn.execute("INSERT INTO messages (id, conv_id, role, content, citations, created_at) VALUES (?,?,?,?,?,?)",
                     (mid, conv_id, role, content, json.dumps(citations), time.time()))
        title = (content[:60] + "…") if len(content) > 60 else content
        if role == "user":
            conn.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, time.time(), conv_id))
        else:
            conn.execute("UPDATE conversations SET updated_at=? WHERE id=?", (time.time(), conv_id))
        conn.commit()
    finally:
        conn.close()
    return mid


@app.post("/api/chat")
async def chat_nonstream(body: ChatRequest):
    model = model_or_fallback(body.model)
    ready, msg = await ensure_chat_model(model)
    if not ready:
        raise HTTPException(503, msg)
    cid = body.conversation_id
    if not cid:
        cid = (await new_conv())["id"]
    chunks, nq = await retrieval.retrieve(body.message, top_k=body.top_k, doc_ids=body.doc_ids, filename=body.filename)
    context = retrieval.build_context(chunks)
    conn = db.connect()
    try:
        rows = conn.execute("SELECT role, content FROM messages WHERE conv_id=? ORDER BY created_at DESC LIMIT 8", (cid,)).fetchall()
        hist = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    finally:
        conn.close()
    # keep history chars bounded
    messages = prompts.chat_prompt(body.message, context, hist, body.language)
    try:
        answer = await ollama_client.chat(messages, model=model)
    except Exception as e:
        raise HTTPException(502, f"Local model error: {e}. Try a smaller model in Settings.")
    cits = retrieval.format_citations(chunks)
    save_message(cid, "user", body.message, [])
    save_message(cid, "assistant", answer, cits)
    return {"conversation_id": cid, "answer": answer, "citations": cits, "chunks_used": len(chunks), "normalized_query": nq}


@app.post("/api/chat/stream")
async def chat_stream(body: ChatRequest):
    model = model_or_fallback(body.model)
    ready, msg = await ensure_chat_model(model)
    if not ready:
        raise HTTPException(503, msg)
    cid = body.conversation_id or (await new_conv())["id"]
    chunks, nq = await retrieval.retrieve(body.message, top_k=body.top_k, doc_ids=body.doc_ids, filename=body.filename)
    context = retrieval.build_context(chunks)
    conn = db.connect()
    try:
        rows = conn.execute("SELECT role, content FROM messages WHERE conv_id=? ORDER BY created_at DESC LIMIT 8", (cid,)).fetchall()
        hist = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
    finally:
        conn.close()
    messages = prompts.chat_prompt(body.message, context, hist, body.language)
    cits = retrieval.format_citations(chunks)
    save_message(cid, "user", body.message, [])

    async def gen():
        yield sse_wrap("__meta__:" + json.dumps({"conversation_id": cid, "citations": cits, "chunks_used": len(chunks)}))
        full: list[str] = []
        try:
            async for delta in ollama_client.chat_stream(messages, model=model):
                full.append(delta)
                yield sse_wrap(delta)
        except Exception as e:
            yield sse_wrap(f"\n[Local model error: {e}]")
        save_message(cid, "assistant", "".join(full), cits)
        yield "data: [DONE]\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


class ExplainRequest(BaseModel):
    topic: str
    doc_ids: Optional[list[str]] = None
    language: str = "auto"
    model: Optional[str] = None


@app.post("/api/study/explain")
async def explain(body: ExplainRequest):
    model = model_or_fallback(body.model)
    ready, msg = await ensure_chat_model(model)
    if not ready:
        raise HTTPException(503, msg)
    chunks, _ = await retrieval.retrieve(body.topic, doc_ids=body.doc_ids)
    context = retrieval.build_context(chunks)
    messages = prompts.explain_prompt(body.topic, context, body.language)
    answer = await ollama_client.chat(messages, model=model)
    return {"answer": answer, "citations": retrieval.format_citations(chunks)}


class SummaryRequest(BaseModel):
    doc_ids: Optional[list[str]] = None
    filename: Optional[str] = None
    topic: Optional[str] = None
    language: str = "auto"
    model: Optional[str] = None
    max_pages: int = 12


@app.post("/api/study/summarize")
async def summarize(body: SummaryRequest):
    model = model_or_fallback(body.model)
    ready, msg = await ensure_chat_model(model)
    if not ready:
        raise HTTPException(503, msg)
    scope = body.filename or (", ".join(body.doc_ids) if body.doc_ids else "all lectures")
    if body.topic:
        chunks, _ = await retrieval.retrieve(body.topic, top_k=10, doc_ids=body.doc_ids, filename=body.filename)
        scope_title = f"topic '{body.topic}' in {scope}"
    elif body.filename or body.doc_ids:
        # gather representative chunks: first chunks of each doc (ordered)
        conn = db.connect()
        try:
            if body.filename:
                rows = conn.execute("SELECT * FROM chunks WHERE filename=? ORDER BY page, chunk_index LIMIT ?", (body.filename, body.max_pages * 2)).fetchall()
            else:
                qm = ",".join(["?"] * len(body.doc_ids or []))
                rows = conn.execute(f"SELECT * FROM chunks WHERE doc_id IN ({qm}) ORDER BY filename, page, chunk_index LIMIT ?", (*(body.doc_ids or []), body.max_pages * 2)).fetchall()
            chunks = [{"id": r["id"], "text": r["text"], "filename": r["filename"], "doc_id": r["doc_id"], "page": r["page"], "chunk_index": r["chunk_index"], "heading": r["heading"] or "", "score": 1.0} for r in rows]
        finally:
            conn.close()
        scope_title = scope
    else:
        raise HTTPException(400, "Select a lecture or provide a topic.")
    if not chunks:
        raise HTTPException(404, "No content found for that selection.")
    context = retrieval.build_context(chunks, max_chars=config.MAX_CONTEXT_CHARS)
    messages = prompts.summary_prompt(context, scope_title, body.language)
    answer = await ollama_client.chat(messages, model=model, max_tokens=1400)
    # persist
    sid = uuid.uuid4().hex[:12]
    conn = db.connect()
    try:
        conn.execute("INSERT INTO summaries (id, title, scope, content, created_at) VALUES (?,?,?,?,?)", (sid, scope_title[:120], scope_title[:300], answer, time.time()))
        conn.commit()
    finally:
        conn.close()
    # coverage honesty
    conn = db.connect()
    try:
        if body.filename:
            d = conn.execute("SELECT page_count, chunk_count FROM documents WHERE filename=?", (body.filename,)).fetchone()
            coverage = f"Summary based on up to {len(chunks)} chunks from {body.filename}." + (f" Document has {d['page_count']} pages." if d else "")
        else:
            coverage = f"Summary based on {len(chunks)} retrieved chunks ({scope_title}). May not cover entire course."
    finally:
        conn.close()
    return {"id": sid, "title": scope_title, "summary": answer, "citations": retrieval.format_citations(chunks), "coverage": coverage}


@app.get("/api/study/summaries")
async def list_summaries():
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM summaries ORDER BY created_at DESC LIMIT 50").fetchall()
        return {"summaries": [dict(r) for r in rows]}
    finally:
        conn.close()


class FlashRequest(BaseModel):
    doc_ids: Optional[list[str]] = None
    filename: Optional[str] = None
    topic: Optional[str] = None
    count: int = 10
    model: Optional[str] = None


@app.post("/api/study/flashcards/generate")
async def gen_flash(body: FlashRequest):
    from .prompts import SYSTEM_FLASH
    model = model_or_fallback(body.model)
    ready, msg = await ensure_chat_model(model)
    if not ready:
        raise HTTPException(503, msg)
    count = max(3, min(30, body.count))
    seed_q = body.topic or "key concepts, definitions, processes"
    chunks, _ = await retrieval.retrieve(seed_q, top_k=10, doc_ids=body.doc_ids, filename=body.filename)
    if not chunks:
        raise HTTPException(404, "Not enough material for flashcards in this selection.")
    context = retrieval.build_context(chunks)
    messages = [
        {"role": "system", "content": SYSTEM_FLASH},
        {"role": "user", "content": f"Excerpts:\n{context}\n\nCreate {count} flashcards."},
    ]
    raw = await ollama_client.chat(messages, model=model, max_tokens=1600)
    cards = parse_json_array(raw)
    # fallback: build naive cards from chunks if LLM returned garbage
    if not cards:
        cards = [{"front": f"Explain: {(c.get('heading') or c['filename'] + ' p.' + str(c['page']))}", "back": c["text"][:400]} for c in chunks[:count]]
    cards = cards[:count]
    conn = db.connect()
    saved = []
    try:
        for cd in cards:
            fid = uuid.uuid4().hex[:12]
            front = str(cd.get("front", ""))[:800]
            back = str(cd.get("back", ""))[:1500]
            if not front or not back:
                continue
            src = "; ".join(sorted({f"[{c['filename']}, page {c['page']}]" for c in chunks[:4]}))
            conn.execute("INSERT INTO flashcards (id, front, back, doc_ids, source, status, created_at) VALUES (?,?,?,?,?,?,?)",
                         (fid, front, back, json.dumps(body.doc_ids or []), src, "new", time.time()))
            saved.append({"id": fid, "front": front, "back": back, "source": src, "status": "new"})
        conn.commit()
    finally:
        conn.close()
    return {"flashcards": saved, "citations": retrieval.format_citations(chunks)}


def parse_json_array(raw: str) -> list[dict]:
    import re as _re
    t = raw.strip()
    # strip fences
    t = _re.sub(r"^```(json)?", "", t).strip()
    t = _re.sub(r"```$", "", t).strip()
    try:
        v = json.loads(t)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
        if isinstance(v, dict) and isinstance(v.get("flashcards"), list):
            return v["flashcards"]
        if isinstance(v, dict) and isinstance(v.get("questions"), list):
            return v["questions"]
    except Exception:
        pass
    # try to find first [...] block
    m = _re.search(r"\[.*\]", t, _re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
        except Exception:
            pass
    return []


@app.get("/api/study/flashcards")
async def list_flash(status: Optional[str] = None):
    conn = db.connect()
    try:
        if status:
            rows = conn.execute("SELECT * FROM flashcards WHERE status=? ORDER BY created_at DESC LIMIT 300", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM flashcards ORDER BY created_at DESC LIMIT 300").fetchall()
        return {"flashcards": [dict(r) for r in rows]}
    finally:
        conn.close()


@app.post("/api/study/flashcards/{fid}/mark")
async def mark_flash(fid: str, status: str = Form("known")):
    if status not in ("new", "known", "difficult"):
        raise HTTPException(400, "bad status")
    conn = db.connect()
    try:
        conn.execute("UPDATE flashcards SET status=? WHERE id=?", (status, fid))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.delete("/api/study/flashcards/{fid}")
async def del_flash(fid: str):
    conn = db.connect()
    try:
        conn.execute("DELETE FROM flashcards WHERE id=?", (fid,))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


class ExamGenRequest(BaseModel):
    doc_ids: Optional[list[str]] = None
    filename: Optional[str] = None
    topic: Optional[str] = None
    count: int = 8
    difficulty: str = "medium"
    model: Optional[str] = None


@app.post("/api/study/exam/generate")
async def exam_generate(body: ExamGenRequest):
    from .prompts import SYSTEM_EXAM
    model = model_or_fallback(body.model)
    ready, msg = await ensure_chat_model(model)
    if not ready:
        raise HTTPException(503, msg)
    count = max(2, min(20, body.count))
    seed = body.topic or "most important examinable concepts"
    chunks, _ = await retrieval.retrieve(f"{seed} ({body.difficulty} difficulty)", top_k=10, doc_ids=body.doc_ids, filename=body.filename)
    if not chunks:
        raise HTTPException(404, "Not enough material to build a reliable quiz for this selection.")
    context = retrieval.build_context(chunks)
    messages = [
        {"role": "system", "content": SYSTEM_EXAM},
        {"role": "user", "content": f"Excerpts:\n{context}\n\nCreate {count} questions, difficulty {body.difficulty}. Mix MCQ and open-ended."},
    ]
    raw = await ollama_client.chat(messages, model=model, max_tokens=2000)
    questions = parse_questions(raw, count)
    if not questions:
        raise HTTPException(502, "The model did not return usable questions. Try fewer questions or a narrower topic.")
    if len(questions) < count:
        note = f"Only {len(questions)} reliable question(s) could be built from the material (requested {count})."
    else:
        note = ""
    aid = uuid.uuid4().hex[:12]
    cfg = {"doc_ids": body.doc_ids or [], "filename": body.filename, "topic": body.topic, "difficulty": body.difficulty, "note": note}
    conn = db.connect()
    try:
        conn.execute("INSERT INTO exam_attempts (id, kind, config, questions, answers, score, total, feedback, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (aid, "practice", json.dumps(cfg), json.dumps(questions), "{}", 0, len(questions), "[]", time.time()))
        conn.commit()
    finally:
        conn.close()
    return {"attempt_id": aid, "questions": hide_answers(questions), "note": note, "citations": retrieval.format_citations(chunks)}


def parse_questions(raw: str, want: int) -> list[dict]:
    import re as _re
    t = raw.strip()
    t = _re.sub(r"^```(json)?", "", t).strip()
    t = _re.sub(r"```$", "", t).strip()
    try:
        v = json.loads(t)
        qs = v.get("questions", v if isinstance(v, list) else [])
        return [q for q in qs if isinstance(q, dict) and q.get("question")][:want]
    except Exception:
        pass
    m = _re.search(r"\{.*\}", t, _re.DOTALL)
    if m:
        try:
            v = json.loads(m.group(0))
            qs = v.get("questions", [])
            return [q for q in qs if isinstance(q, dict) and q.get("question")][:want]
        except Exception:
            return []
    return []


def hide_answers(qs: list[dict]) -> list[dict]:
    out = []
    for i, q in enumerate(qs):
        out.append({"index": i, "type": q.get("type", "mcq"), "question": q.get("question", ""), "options": q.get("options", []), "source": q.get("source", "")})
    return out


class ExamSubmit(BaseModel):
    attempt_id: str
    answers: dict
    model: Optional[str] = None


@app.post("/api/study/exam/submit")
async def exam_submit(body: ExamSubmit):
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM exam_attempts WHERE id=?", (body.attempt_id,)).fetchone()
        if not row:
            raise HTTPException(404, "attempt not found")
        att = dict(row)
    finally:
        conn.close()
    questions = json.loads(att["questions"])
    feedback = []
    score = 0
    # grade MCQ locally (exact); open-ended via LLM
    open_items = []
    for i, q in enumerate(questions):
        given = str(body.answers.get(str(i), body.answers.get(i, ""))).strip()
        correct = str(q.get("answer", "")).strip()
        qtype = q.get("type", "mcq")
        if qtype == "mcq":
            # accept letter match (A/B/C/D) case-insensitive
            g = given.upper().replace(")", "").strip()[:1]
            c = correct.upper().replace(")", "").strip()[:1]
            ok = bool(g and c and g == c)
            if ok:
                score += 1
            feedback.append({"index": i, "correct": ok, "given": given, "expected": correct, "explanation": q.get("explanation", ""), "source": q.get("source", "")})
        else:
            open_items.append((i, q, given))
    if open_items:
        model = model_or_fallback(body.model)
        chunks_hint = ""
        try:
            fb_prompt = [
                {"role": "system", "content": "Grade open-ended answers briefly. Return ONLY JSON: [{\"index\": N, \"correct\": true/false, \"expected\": \"...\", \"explanation\": \"...\"}]. Partial credit: mark true if substantially correct."},
                {"role": "user", "content": json.dumps([{"index": i, "question": q.get("question"), "reference_answer": q.get("answer"), "student_answer": g} for i, q, g in open_items])[:6000]},
            ]
            raw = await ollama_client.chat(fb_prompt, model=model, max_tokens=1200)
            graded = parse_json_array(raw)
            gmap = {int(x.get("index", -1)): x for x in graded if isinstance(x, dict)}
            for i, q, g in open_items:
                gi = gmap.get(i)
                if gi and gi.get("correct"):
                    score += 1
                    feedback.append({"index": i, "correct": True, "given": g, "expected": q.get("answer", ""), "explanation": gi.get("explanation", q.get("explanation", "")), "source": q.get("source", "")})
                else:
                    feedback.append({"index": i, "correct": False, "given": g, "expected": q.get("answer", "") if not gi else gi.get("expected", q.get("answer", "")), "explanation": (gi or {}).get("explanation", q.get("explanation", "")), "source": q.get("source", "")})
        except Exception:
            for i, q, g in open_items:
                feedback.append({"index": i, "correct": False, "given": g, "expected": q.get("answer", ""), "explanation": q.get("explanation", ""), "source": q.get("source", "")})
    feedback.sort(key=lambda x: x["index"])
    conn = db.connect()
    try:
        conn.execute("UPDATE exam_attempts SET answers=?, score=?, total=?, feedback=? WHERE id=?",
                     (json.dumps(body.answers), score, len(questions), json.dumps(feedback), body.attempt_id))
        conn.commit()
    finally:
        conn.close()
    return {"score": score, "total": len(questions), "feedback": feedback}


@app.get("/api/study/exam/attempts")
async def exam_attempts():
    conn = db.connect()
    try:
        rows = conn.execute("SELECT id, kind, config, score, total, created_at FROM exam_attempts ORDER BY created_at DESC LIMIT 50").fetchall()
        return {"attempts": [dict(r) for r in rows]}
    finally:
        conn.close()


# ---------------- static frontend ----------------
FRONT_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

@app.get("/")
async def root_index():
    idx = FRONT_DIST / "index.html"
    if idx.exists():
        return FileResponse(str(idx), media_type="text/html")
    return {"app": "study-assistant-local", "frontend": "not built — run npm run build or use dev server :5173", "api_docs": "/docs"}


if FRONT_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONT_DIST / "assets")), name="assets")
