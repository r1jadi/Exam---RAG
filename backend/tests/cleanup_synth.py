import sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.app import vectorstore

conn = sqlite3.connect(str(ROOT / "data" / "app.db"))
rows = conn.execute("SELECT id, filename, file_path FROM documents WHERE filename=?", ("Database_Lecture_04.pdf",)).fetchall()
print("test docs:", len(rows))
for r in rows:
    doc_id = r[0]
    conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
    conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    vectorstore.delete_by_doc(doc_id)
    try:
        Path(r[2]).unlink(missing_ok=True)
    except Exception as e:
        print("unlink warn", e)
conn.commit()
conn.close()
print("cleaned")
