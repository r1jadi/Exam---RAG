"""E2E: synthetic PDF -> ingest -> retrieve -> chat. Uses real Ollama + Chroma + SQLite."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from backend.app import config, db, ingest, retrieval, ollama_client

PDF = ROOT / "data" / "test_synth.pdf"

def make_pdf():
    config.ensure_dirs()
    c = canvas.Canvas(str(PDF), pagesize=letter)
    pages = [
        "Database Lecture 04\nNormalization\nFirst normal form 1NF removes repeating groups. Example: a Students table with multiple phone columns violates 1NF.",
        "Database Lecture 04 continued\nSecond normal form 2NF requires 1NF plus no partial dependency on part of a composite key. Third normal form 3NF removes transitive dependencies.",
        "Operating Systems Lecture 02\nPaging divides memory into fixed-size pages. Page tables map virtual pages to physical frames. TLB caches translations.",
    ]
    for t in pages:
        y = 720
        for line in t.split("\n"):
            c.drawString(72, y, line)
            y -= 18
        c.showPage()
    c.save()
    print(f"synthetic PDF: {PDF} ({PDF.stat().st_size} bytes)")

async def main():
    make_pdf()
    db.init_db()
    # fake upload via register
    import tempfile, shutil
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        shutil.copyfile(PDF, tmp.name)
        tmpp = Path(tmp.name)
    reg = ingest.register_document("Database_Lecture_04.pdf", tmpp, PDF.stat().st_size)
    try:
        tmpp.unlink()
    except Exception:
        pass
    doc = reg["document"] if not reg.get("duplicate") else reg["document"]
    # if duplicate from previous run, find fresh by re-register with different name? just reindex existing
    print("doc:", doc["id"], doc["filename"], "dup:", reg.get("duplicate"))
    info = await ingest.index_document(doc["id"])
    print("indexed:", info)
    assert info["pages"] == 3, info
    assert info["chunks"] >= 3, info

    chunks, nq = await retrieval.retrieve("What is third normal form 3NF?")
    print("retrieved:", len(chunks), "norm:", nq)
    for ch in chunks[:3]:
        print(" -", ch["filename"], "p", ch["page"], "score", ch["score"], (ch["text"][:100].replace(chr(10), " ")))
    assert chunks, "no chunks retrieved"
    assert any("3NF" in ch["text"] or "third" in ch["text"].lower() or "transitive" in ch["text"].lower() for ch in chunks), "retrieval missed 3NF content"
    assert chunks[0]["filename"] == "Database_Lecture_04.pdf"
    assert chunks[0]["page"] >= 1

    # chat generation with real local model (small timeout, short answer)
    from backend.app import prompts
    ctx = retrieval.build_context(chunks[:4])
    msgs = prompts.chat_prompt("What is 3NF?", ctx, [], "English")
    ans = await asyncio.wait_for(ollama_client.chat(msgs, max_tokens=250), timeout=240)
    print("answer:", ans[:600])
    assert len(ans) > 20

    # persistence check
    import sqlite3
    conn = sqlite3.connect(str(config.DB_PATH))
    n = conn.execute("SELECT COUNT(*) FROM chunks WHERE doc_id=?", (doc["id"],)).fetchone()[0]
    conn.close()
    print("sqlite chunks:", n)
    assert n == info["chunks"]
    print("E2E OK")

asyncio.run(main())
