import sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import vectorstore
conn = sqlite3.connect(str(ROOT / "data" / "app.db"))
for (doc_id, fp) in conn.execute("SELECT id, file_path FROM documents WHERE filename=?", ("Biology_Lecture_01.pdf",)).fetchall():
    conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    vectorstore.delete_by_doc(doc_id)
    try: Path(fp).unlink(missing_ok=True)
    except Exception: pass
conn.execute("DELETE FROM flashcards")
conn.execute("DELETE FROM exam_attempts")
conn.execute("DELETE FROM conversations")
conn.execute("DELETE FROM messages")
conn.execute("DELETE FROM summaries")
conn.commit()
docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
print("remaining docs:", docs, "vectors:", vectorstore.count())
conn.close()
for p in ["data/bio_test.pdf"]:
    try: (ROOT / p).unlink(missing_ok=True)
    except Exception: pass
print("cleaned study e2e leftovers")
