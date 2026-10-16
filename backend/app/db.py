"""SQLite persistence: documents, chunks, chats, flashcards, exams."""
from __future__ import annotations
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  file_hash TEXT NOT NULL UNIQUE,
  file_path TEXT NOT NULL,
  file_size INTEGER NOT NULL DEFAULT 0,
  page_count INTEGER NOT NULL DEFAULT 0,
  indexed_pages INTEGER NOT NULL DEFAULT 0,
  chunk_count INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT DEFAULT '',
  unreadable_pages TEXT DEFAULT '[]',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL,
  filename TEXT NOT NULL,
  page INTEGER NOT NULL,
  chunk_index INTEGER NOT NULL,
  heading TEXT DEFAULT '',
  text TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(doc_id, page, chunk_index)
);
CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'New chat',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conv_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  citations TEXT DEFAULT '[]',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conv_id);
CREATE TABLE IF NOT EXISTS flashcards (
  id TEXT PRIMARY KEY,
  front TEXT NOT NULL,
  back TEXT NOT NULL,
  doc_ids TEXT DEFAULT '[]',
  source TEXT DEFAULT '',
  status TEXT DEFAULT 'new',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS exam_attempts (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  config TEXT NOT NULL,
  questions TEXT NOT NULL,
  answers TEXT NOT NULL DEFAULT '{}',
  score INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  feedback TEXT NOT NULL DEFAULT '[]',
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS summaries (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  scope TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at REAL NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    config.ensure_dirs()
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    conn = connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def now() -> float:
    return time.time()


def row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    return dict(r)


def list_documents() -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def dashboard_stats() -> dict:
    conn = connect()
    try:
        docs = conn.execute("SELECT COUNT(*) c, COALESCE(SUM(page_count),0) p, COALESCE(SUM(chunk_count),0) ch FROM documents WHERE status='ready'").fetchone()
        convs = conn.execute("SELECT COUNT(*) c FROM conversations").fetchone()
        cards = conn.execute("SELECT COUNT(*) c FROM flashcards").fetchone()
        known = conn.execute("SELECT COUNT(*) c FROM flashcards WHERE status='known'").fetchone()
        exams = conn.execute("SELECT COUNT(*) c FROM exam_attempts").fetchone()
        recent = conn.execute("SELECT id, filename, status, page_count, updated_at FROM documents ORDER BY updated_at DESC LIMIT 5").fetchall()
        return {
            "indexed_documents": docs["c"] or 0,
            "total_pages": docs["p"] or 0,
            "total_chunks": docs["ch"] or 0,
            "conversations": convs["c"] or 0,
            "flashcards_total": cards["c"] or 0,
            "flashcards_known": known["c"] or 0,
            "exam_attempts": exams["c"] or 0,
            "recent_documents": [row_to_dict(r) for r in recent],
        }
    finally:
        conn.close()
