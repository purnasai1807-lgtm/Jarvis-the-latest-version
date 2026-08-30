"""
Long-term memory for Jarvis — Phase 7.

SQLite stores facts in a structured table. FTS5 provides keyword search.
ChromaDB adds semantic (vector) search on top — optional, graceful FTS5 fallback.
"""

import sqlite3
import threading
from pathlib import Path

from loguru import logger

_DEFAULT_DB = Path("data/memory.db")
_DEFAULT_CHROMA = Path("data/chroma")


class MemoryManager:
    """Manages Jarvis's persistent long-term memory across all conversations."""

    def __init__(self, config: dict) -> None:
        self._lock = threading.Lock()
        cfg = config.get("memory", {})
        self._db_path = Path(cfg.get("db_path", _DEFAULT_DB))
        self._chroma_path = Path(cfg.get("chroma_path", _DEFAULT_CHROMA))
        self._max_context = cfg.get("max_context_facts", 5)

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sqlite()
        self._chroma = self._init_chroma()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _init_sqlite(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS facts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    key        TEXT NOT NULL UNIQUE,
                    value      TEXT NOT NULL,
                    category   TEXT NOT NULL DEFAULT 'general',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Standalone FTS5 table — avoids content-table sync complexities
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
                USING fts5(key, value, category)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    summary    TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.commit()
        logger.info(f"Memory SQLite ready: {self._db_path}")

    def _init_chroma(self):
        try:
            import chromadb
            self._chroma_path.mkdir(parents=True, exist_ok=True)
            client = chromadb.PersistentClient(path=str(self._chroma_path))
            collection = client.get_or_create_collection("jarvis_facts")
            logger.info("ChromaDB semantic memory ready")
            return collection
        except Exception as exc:
            logger.warning(f"ChromaDB unavailable (FTS5 fallback active): {exc}")
            return None

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self._db_path, check_same_thread=False)

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def remember(self, key: str, value: str, category: str = "general") -> str:
        """Store or update a fact by key."""
        key = key.strip().lower()
        with self._lock:
            with self._conn() as conn:
                existing = conn.execute(
                    "SELECT id FROM facts WHERE key = ?", (key,)
                ).fetchone()

                if existing:
                    row_id = existing[0]
                    conn.execute(
                        "UPDATE facts SET value=?, category=?, updated_at=datetime('now') WHERE key=?",
                        (value, category, key)
                    )
                    # Keep FTS in sync: delete old entry, insert updated
                    conn.execute("DELETE FROM facts_fts WHERE rowid = ?", (row_id,))
                    conn.execute(
                        "INSERT INTO facts_fts(rowid, key, value, category) VALUES (?,?,?,?)",
                        (row_id, key, value, category)
                    )
                else:
                    cursor = conn.execute(
                        "INSERT INTO facts (key, value, category) VALUES (?,?,?)",
                        (key, value, category)
                    )
                    row_id = cursor.lastrowid
                    conn.execute(
                        "INSERT INTO facts_fts(rowid, key, value, category) VALUES (?,?,?,?)",
                        (row_id, key, value, category)
                    )
                conn.commit()

            # Mirror to ChromaDB for semantic search
            if self._chroma is not None:
                try:
                    self._chroma.upsert(
                        ids=[key],
                        documents=[f"{key}: {value}"],
                        metadatas=[{"category": category, "key": key}],
                    )
                except Exception as exc:
                    logger.warning(f"ChromaDB upsert failed: {exc}")

        logger.info(f"Memory stored [{category}] {key} = {value[:80]}")
        return f"Remembered: {key} = {value}"

    def recall(self, query: str, n: int = 5) -> list[dict]:
        """Semantic search — returns the n most relevant facts for the query."""
        results: list[dict] = []

        # 1. ChromaDB semantic search (preferred)
        if self._chroma is not None:
            try:
                count = self._count_facts()
                if count > 0:
                    res = self._chroma.query(
                        query_texts=[query],
                        n_results=min(n, count),
                    )
                    docs = (res.get("documents") or [[]])[0]
                    metas = (res.get("metadatas") or [[]])[0]
                    dists = (res.get("distances") or [[]])[0]
                    for doc, meta, dist in zip(docs, metas, dists):
                        results.append({
                            "key": meta.get("key", ""),
                            "doc": doc,
                            "score": round(1 - dist, 3),
                            "category": meta.get("category", ""),
                        })
                    if results:
                        return results[:n]
            except Exception as exc:
                logger.warning(f"ChromaDB query failed: {exc}")

        # 2. SQLite FTS5 keyword search
        try:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT f.key, f.value, f.category
                    FROM   facts_fts
                    JOIN   facts f ON facts_fts.rowid = f.id
                    WHERE  facts_fts MATCH ?
                    LIMIT  ?
                """, (query, n)).fetchall()
            for key, value, category in rows:
                results.append({
                    "key": key,
                    "doc": f"{key}: {value}",
                    "score": 1.0,
                    "category": category,
                })
            if results:
                return results[:n]
        except Exception as exc:
            logger.warning(f"FTS5 query failed: {exc}")

        # 3. Last-resort: most-recently-updated facts
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT key, value, category FROM facts ORDER BY updated_at DESC LIMIT ?",
                (n,)
            ).fetchall()
        for key, value, category in rows:
            results.append({
                "key": key,
                "doc": f"{key}: {value}",
                "score": 0.3,
                "category": category,
            })
        return results[:n]

    def recall_exact(self, key: str) -> str | None:
        """Exact key lookup. Returns None if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT value FROM facts WHERE key = ?", (key.strip().lower(),)
            ).fetchone()
        return row[0] if row else None

    def forget(self, key: str) -> str:
        """Delete a fact by key."""
        key = key.strip().lower()
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id FROM facts WHERE key = ?", (key,)
                ).fetchone()
                if not row:
                    return f"No memory found for '{key}'."
                # Delete FTS entry first, then the fact
                conn.execute("DELETE FROM facts_fts WHERE rowid = ?", (row[0],))
                conn.execute("DELETE FROM facts WHERE key = ?", (key,))
                conn.commit()

            if self._chroma is not None:
                try:
                    self._chroma.delete(ids=[key])
                except Exception:
                    pass

        logger.info(f"Memory deleted: {key}")
        return f"Forgotten: {key}"

    def list_facts(self, category: str | None = None) -> list[dict]:
        """Return all facts, newest first, optionally filtered by category."""
        with self._conn() as conn:
            if category:
                rows = conn.execute(
                    "SELECT key, value, category, updated_at FROM facts "
                    "WHERE category = ? ORDER BY updated_at DESC",
                    (category,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT key, value, category, updated_at FROM facts "
                    "ORDER BY updated_at DESC"
                ).fetchall()
        return [
            {"key": r[0], "value": r[1], "category": r[2], "updated_at": r[3]}
            for r in rows
        ]

    def _count_facts(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    # ------------------------------------------------------------------
    # Brain integration
    # ------------------------------------------------------------------

    def get_context_for(self, query: str) -> str:
        """Return a formatted memory block for injection into the system prompt."""
        if not query or self._count_facts() == 0:
            return ""
        try:
            facts = self.recall(query, n=self._max_context)
            lines = [f"- {f['doc']}" for f in facts if f.get("doc")]
            if not lines:
                return ""
            return "Relevant memories about sir:\n" + "\n".join(lines)
        except Exception as exc:
            logger.warning(f"get_context_for failed: {exc}")
            return ""

    def save_conversation_summary(self, summary: str) -> None:
        """Persist a short summary of the current conversation."""
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO conversations (summary) VALUES (?)", (summary,)
            )
            conn.commit()
