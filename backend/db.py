import sqlite3
import os
import json
from typing import Any, Dict, List, Optional
from datetime import datetime, UTC

from .config import DB_PATH
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

ISO = "%Y-%m-%dT%H:%M:%S"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # Ensure foreign key constraints are enforced (needed for ON DELETE CASCADE)
        conn.execute("PRAGMA foreign_keys = ON")
    except Exception:
        pass
    return conn


"""SQLite data access layer

Responsibilities:
- Initialize the database schema
- CRUD operations for PDFs, words, and generated word info

Public API:
- init_db(), insert_pdf(), get_pdf(), add_word(), list_words(), upsert_word_info(), list_pdfs(), delete_word()
"""
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    # pdfs table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pdfs (
            id TEXT PRIMARY KEY,
            original_name TEXT NOT NULL,
            filename TEXT NOT NULL,
            uploaded_at TEXT NOT NULL
        )
        """
    )
    # words table
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_id TEXT NOT NULL,
            word TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(pdf_id, word),
            FOREIGN KEY(pdf_id) REFERENCES pdfs(id) ON DELETE CASCADE
        )
        """
    )
    # word_info table - one-to-one with words
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS word_info (
            word_id INTEGER PRIMARY KEY,
            data_json TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            FOREIGN KEY(word_id) REFERENCES words(id) ON DELETE CASCADE
        )
        """
    )
    conn.commit()
    conn.close()


def insert_pdf(pdf_id: str, original_name: str, filename: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR REPLACE INTO pdfs (id, original_name, filename, uploaded_at) VALUES (?, ?, ?, ?)",
        (pdf_id, original_name, filename, datetime.now(UTC).strftime(ISO)),
    )
    conn.commit()
    conn.close()


def get_pdf(pdf_id: str) -> Optional[sqlite3.Row]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM pdfs WHERE id=?", (pdf_id,))
    row = cur.fetchone()
    conn.close()
    return row


def add_word(pdf_id: str, word: str) -> Dict[str, Any]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO words (pdf_id, word, created_at) VALUES (?, ?, ?)",
        (pdf_id, word, datetime.now(UTC).strftime(ISO)),
    )
    conn.commit()
    cur.execute("SELECT * FROM words WHERE pdf_id=? AND word=?", (pdf_id, word))
    row = dict(cur.fetchone())
    conn.close()
    return row


def list_words(pdf_id: str) -> List[Dict[str, Any]]:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT w.id, w.word, w.created_at, wi.data_json, wi.generated_at
        FROM words w
        LEFT JOIN word_info wi ON wi.word_id = w.id
        WHERE w.pdf_id=?
        ORDER BY w.created_at ASC
        """,
        (pdf_id,),
    )
    rows = [dict(r) for r in cur.fetchall()]
    for r in rows:
        if r.get("data_json"):
            try:
                r["data"] = json.loads(r["data_json"])  # expand
            except Exception:
                r["data"] = None
        r.pop("data_json", None)
    conn.close()
    return rows


def get_word_with_data(pdf_id: str, word: str) -> Optional[Dict[str, Any]]:
    """Return a single word row (joined with any generated info) for a PDF.

    Includes fields: id, word, created_at, data (if present), generated_at (if present).
    """
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT w.id, w.word, w.created_at, wi.data_json, wi.generated_at
        FROM words w
        LEFT JOIN word_info wi ON wi.word_id = w.id
        WHERE w.pdf_id = ? AND w.word = ?
        LIMIT 1
        """,
        (pdf_id, word),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return None
    data = dict(row)
    dj = data.pop('data_json', None)
    if dj:
        try:
            data['data'] = json.loads(dj)
        except Exception:
            data['data'] = None
    return data


def upsert_word_info(word_id: int, data: Dict[str, Any]):
    conn = get_conn()
    cur = conn.cursor()
    payload = json.dumps(data, ensure_ascii=False)
    now = datetime.now(UTC).strftime(ISO)
    cur.execute(
        "INSERT INTO word_info (word_id, data_json, generated_at) VALUES (?, ?, ?)\n         ON CONFLICT(word_id) DO UPDATE SET data_json=excluded.data_json, generated_at=excluded.generated_at",
        (word_id, payload, now),
    )
    conn.commit()
    conn.close()


def list_pdfs() -> List[Dict[str, Any]]:
    """Return all PDFs with a word count for quick overview."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.id, p.original_name, p.filename, p.uploaded_at,
               (
                 SELECT COUNT(1) FROM words w WHERE w.pdf_id = p.id
               ) AS word_count
        FROM pdfs p
        ORDER BY p.uploaded_at DESC
        """
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def delete_word(word_id: int) -> bool:
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM words WHERE id=?", (word_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def delete_pdf(pdf_id: str) -> bool:
    """Delete a PDF row by id. With foreign keys enabled, cascades to words/word_info."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM pdfs WHERE id=?", (pdf_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted
