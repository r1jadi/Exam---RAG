"""PDF ingestion: hash, page-by-page extraction, chunking, OCR fallback notice."""
from __future__ import annotations
import hashlib
import re
import time
import uuid
from pathlib import Path
from typing import Optional

import pymupdf

from . import config, db, vectorstore
from . import ollama_client

HEADING_RE = re.compile(r"^(chapter|lecture|section|unit|\d+(\.\d+)*)[\s:.-]+(.+)", re.IGNORECASE)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(blk)
    return h.hexdigest()


def guess_heading(text: str) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for ln in lines[:5]:
        if len(ln) < 120 and (ln[0].isupper() or HEADING_RE.match(ln)):
            # prefer short title-like first line
            return ln[:120]
    return ""


def chunk_page_text(text: str, chunk_chars: Optional[int] = None, overlap: Optional[int] = None) -> list[str]:
    chunk_chars = chunk_chars or config.CHUNK_CHARS
    overlap = overlap if overlap is not None else config.CHUNK_OVERLAP
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_chars:
        return [text]
    chunks: list[str] = []
    start = 0
    # split on sentence-ish boundaries when possible
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        if end < len(text):
            # try to break at last period/newline within last 200 chars
            window = text[max(start, end - 220) : end]
            cut = max(window.rfind(". "), window.rfind("\n"), window.rfind("; "))
            if cut > 40:
                end = max(start, end - 220) + cut + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        if len(chunks) > 40:  # safety per page
            break
    return [c for c in chunks if c]


def extract_pages(pdf_path: Path) -> tuple[list[dict], list[int]]:
    """Returns (pages, unreadable_pages). pages: [{page, text}]."""
    doc = pymupdf.open(str(pdf_path))
    pages: list[dict] = []
    unreadable: list[int] = []
    try:
        for i, pg in enumerate(doc):
            pno = i + 1
            try:
                txt = pg.get_text("text") or ""
            except Exception:
                txt = ""
            txt = txt.strip()
            if len(txt) < 20:
                # Try lightweight OCR if available, else mark unreadable
                ocr_text = try_ocr_page(pg)
                if ocr_text and len(ocr_text.strip()) >= 20:
                    txt = ocr_text.strip()
                else:
                    if not txt:
                        unreadable.append(pno)
            pages.append({"page": pno, "text": txt})
    finally:
        doc.close()
    return pages, unreadable


def try_ocr_page(page) -> str:
    """Local OCR fallback using Tesseract if installed. Returns '' when unavailable."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except Exception:
        return ""
    try:
        pix = page.get_pixmap(dpi=150)
        import io as _io
        img = Image.open(_io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img) or ""
    except Exception:
        return ""


def register_document(filename: str, tmp_path: Path, file_size: int) -> dict:
    file_hash = sha256_file(tmp_path)
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM documents WHERE file_hash=?", (file_hash,)).fetchone()
        if row:
            return {"duplicate": True, "document": dict(row)}
        doc_id = uuid.uuid4().hex[:12]
        dest = config.PDF_DIR / f"{doc_id}_{filename}"
        # stream copy (no big RAM)
        with open(tmp_path, "rb") as src, open(dest, "wb") as dst:
            for blk in iter(lambda: src.read(1024 * 1024), b""):
                dst.write(blk)
        now = time.time()
        conn.execute(
            "INSERT INTO documents (id, filename, file_hash, file_path, file_size, page_count, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (doc_id, filename, file_hash, str(dest), file_size, 0, "pending", now, now),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
        return {"duplicate": False, "document": dict(row)}
    finally:
        conn.close()


async def index_document(doc_id: str, progress_cb=None) -> dict:
    """Full indexing: extract, chunk (dedup), embed, store. Resumable + idempotent."""
    conn = db.connect()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        raise ValueError("document not found")
    doc = dict(row)
    pdf_path = Path(doc["file_path"])

    def set_status(status: str, error: str = "", **kw):
        c = db.connect()
        try:
            c.execute("UPDATE documents SET status=?, error=?, updated_at=? WHERE id=?", (status, error, time.time(), doc_id))
            for k, v in kw.items():
                c.execute(f"UPDATE documents SET {k}=?, updated_at=? WHERE id=?", (v, time.time(), doc_id))
            c.commit()
        finally:
            c.close()

    set_status("indexing", "")
    try:
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file missing: {pdf_path}")
        pages, unreadable = extract_pages(pdf_path)
        page_count = len(pages)

        # Clear previous chunks for re-index (idempotent, prevents duplicates)
        c = db.connect()
        try:
            c.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            c.commit()
        finally:
            c.close()
        vectorstore.delete_by_doc(doc_id)

        all_chunks: list[dict] = []
        for p in pages:
            txt = p["text"]
            if not txt.strip():
                continue
            heading = guess_heading(txt)
            parts = chunk_page_text(txt)
            if not parts and txt.strip():
                parts = [txt.strip()[: config.CHUNK_CHARS]]
            for idx, part in enumerate(parts):
                cid = f"{doc_id}-p{p['page']}-{idx}"
                all_chunks.append({
                    "id": cid,
                    "doc_id": doc_id,
                    "filename": doc["filename"],
                    "page": p["page"],
                    "chunk_index": idx,
                    "heading": heading,
                    "text": part,
                })

        # Persist chunk metadata in SQLite (streaming, no RAM blowup)
        c = db.connect()
        try:
            for ch in all_chunks:
                c.execute(
                    "INSERT OR REPLACE INTO chunks (id, doc_id, filename, page, chunk_index, heading, text, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (ch["id"], ch["doc_id"], ch["filename"], ch["page"], ch["chunk_index"], ch["heading"], ch["text"], time.time()),
                )
            c.commit()
        finally:
            c.close()

        # Embed in small batches (8 per ollama_client batch) and add to Chroma incrementally
        col = vectorstore.get_collection()
        texts = [ch["text"] for ch in all_chunks]
        B = 16
        embedded = 0
        for s in range(0, len(texts), B):
            batch = all_chunks[s : s + B]
            embs = await ollama_client.embed([b["text"] for b in batch])
            col.upsert(
                ids=[b["id"] for b in batch],
                embeddings=embs,
                documents=[b["text"] for b in batch],
                metadatas=[{"doc_id": b["doc_id"], "filename": b["filename"], "page": b["page"], "chunk_index": b["chunk_index"], "heading": b["heading"] or ""} for b in batch],
            )
            embedded += len(batch)
            if progress_cb:
                try:
                    progress_cb(embedded, len(all_chunks))
                except Exception:
                    pass

        import json as _json
        conn2 = db.connect()
        try:
            conn2.execute(
                "UPDATE documents SET status='ready', error=?, page_count=?, indexed_pages=?, chunk_count=?, unreadable_pages=?, updated_at=? WHERE id=?",
                ("", page_count, page_count - len(unreadable), len(all_chunks), _json.dumps(unreadable), time.time(), doc_id),
            )
            conn2.commit()
        finally:
            conn2.close()
        warn = ""
        if unreadable:
            warn = f"{len(unreadable)} page(s) had no extractable text (scanned?). Install Tesseract OCR for those pages: {unreadable[:20]}"
        return {"doc_id": doc_id, "pages": page_count, "chunks": len(all_chunks), "unreadable_pages": unreadable, "warning": warn}
    except Exception as e:
        err = str(e)
        if "Connection" in err or "connect" in err.lower():
            err = f"Ollama/embedding model unavailable: {e}. Start Ollama and pull {config.EMBED_MODEL}."
        set_status("error", err[:2000])
        raise
