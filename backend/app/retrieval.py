"""Hybrid retrieval: semantic (Chroma) + keyword (SQLite LIKE) + light rerank."""
from __future__ import annotations
import re
import sqlite3
from typing import Optional

from . import config, db, vectorstore
from . import ollama_client

STOP = set("the a an and or of to in on for with is are was were be by as at from that this it its into about per faq what when where which who how why explain define describe list give tell me my i we you do does did can could should would will".split())


def normalize_query(q: str) -> str:
    q = (q or "").strip()
    q = re.sub(r"\s+", " ", q)
    return q


def keywords(q: str, limit: int = 8) -> list[str]:
    toks = re.findall(r"[A-Za-zÀ-ÿ0-9_]{3,}", q.lower())
    out = [t for t in toks if t not in STOP]
    seen, res = set(), []
    for t in out:
        if t not in seen:
            seen.add(t)
            res.append(t)
        if len(res) >= limit:
            break
    return res


async def retrieve(query: str, top_k: Optional[int] = None, doc_ids: Optional[list[str]] = None, filename: Optional[str] = None) -> tuple[list[dict], str]:
    """Returns (chunks, normalized_query). Each chunk: {id, text, filename, page, chunk_index, heading, score, source}."""
    top_k = top_k or config.RETRIEVAL_TOP_K
    nq = normalize_query(query)
    if not nq:
        return [], nq
    emb = await ollama_client.embed([nq])
    qvec = emb[0] if emb else None
    sem: list[dict] = []
    if qvec is not None:
        col = vectorstore.get_collection()
        where = None
        if doc_ids:
            where = {"doc_id": {"$in": doc_ids}}
        try:
            res = col.query(query_embeddings=[qvec], n_results=min(max(top_k * 3, top_k), 30), where=where, include=["documents", "metadatas", "distances"])
        except Exception:
            res = None
        if res and res.get("ids"):
            ids = res["ids"][0]
            docs = (res.get("documents") or [[]])[0]
            metas = (res.get("metadatas") or [[]])[0]
            dists = (res.get("distances") or [[]])[0]
            for i, cid in enumerate(ids):
                m = metas[i] or {}
                if filename and m.get("filename") != filename:
                    continue
                if doc_ids and m.get("doc_id") not in doc_ids:
                    continue
                dist = dists[i] if i < len(dists) else 1.0
                sem_score = max(0.0, 1.0 - float(dist))
                sem.append({
                    "id": cid,
                    "text": docs[i] if i < len(docs) else "",
                    "filename": m.get("filename", ""),
                    "doc_id": m.get("doc_id", ""),
                    "page": int(m.get("page", 0) or 0),
                    "chunk_index": int(m.get("chunk_index", 0) or 0),
                    "heading": m.get("heading", "") or "",
                    "sem_score": sem_score,
                    "kw_score": 0.0,
                })
    # Keyword search in SQLite
    kws = keywords(nq)
    kw_hits: dict[str, tuple[float, dict]] = {}
    if kws:
        conn = db.connect()
        try:
            # build OR LIKE query
            conds = " OR ".join(["text LIKE ?"] * len(kws))
            params: list = [f"%{k}%" for k in kws]
            sql = f"SELECT id, doc_id, filename, page, chunk_index, heading, text FROM chunks WHERE ({conds})"
            if doc_ids:
                qmarks = ",".join(["?"] * len(doc_ids))
                sql += f" AND doc_id IN ({qmarks})"
                params += doc_ids
            if filename:
                sql += " AND filename=?"
                params.append(filename)
            sql += " LIMIT 60"
            rows = conn.execute(sql, params).fetchall()
            ql = nq.lower()
            for r in rows:
                d = dict(r)
                t = (d["text"] or "").lower()
                hits = sum(1 for k in kws if k in t)
                score = hits / max(1, len(kws))
                # phrase bonus
                if ql[:40] in t[:4000]:
                    score += 0.2
                prev = kw_hits.get(d["id"])
                if prev is None or score > prev[0]:
                    kw_hits[d["id"]] = (min(1.0, score), d)
        finally:
            conn.close()
    # Merge
    merged: dict[str, dict] = {}
    for s in sem:
        merged[s["id"]] = {**s, "source": "semantic"}
    for cid, (ks, d) in kw_hits.items():
        if cid in merged:
            merged[cid]["kw_score"] = ks
            merged[cid]["source"] = "hybrid"
        else:
            merged[cid] = {
                "id": cid,
                "text": d["text"],
                "filename": d["filename"],
                "doc_id": d["doc_id"],
                "page": d["page"],
                "chunk_index": d["chunk_index"],
                "heading": d.get("heading", "") or "",
                "sem_score": 0.0,
                "kw_score": ks,
                "source": "keyword",
            }
    ranked: list[dict] = []
    for c in merged.values():
        # weighted rerank: semantic matters most, keyword boosts
        c["score"] = round(0.75 * c.get("sem_score", 0.0) + 0.25 * c.get("kw_score", 0.0), 4)
        ranked.append(c)
    ranked.sort(key=lambda x: x["score"], reverse=True)
    # Drop very weak keyword-only noise when semantic exists
    top = ranked[:top_k]
    return top, nq


def build_context(chunks: list[dict], max_chars: Optional[int] = None) -> str:
    max_chars = max_chars or config.MAX_CONTEXT_CHARS
    parts: list[str] = []
    total = 0
    for c in chunks:
        head = f"[{c['filename']}, page {c['page']}]"
        if c.get("heading"):
            head += f" ({c['heading']})"
        block = f"{head}\n{c['text']}\n"
        if total + len(block) > max_chars:
            # include truncated last block if room
            room = max_chars - total
            if room > 400:
                parts.append(block[:room] + "\n[truncated]")
            break
        parts.append(block)
        total += len(block)
    return "\n---\n".join(parts)


def format_citations(chunks: list[dict]) -> list[dict]:
    out = []
    for c in chunks:
        out.append({
            "filename": c["filename"],
            "page": c["page"],
            "chunk_index": c.get("chunk_index", 0),
            "heading": c.get("heading", ""),
            "excerpt": (c.get("text", "")[:320] + ("…" if len(c.get("text", "")) > 320 else "")),
            "doc_id": c.get("doc_id", ""),
            "label": f"[{c['filename']}, page {c['page']}]",
        })
    return out
