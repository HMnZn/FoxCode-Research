"""Project-centric memory persisted in SQLite, with an FTS5 search index."""
import re
import sqlite3
import time
from dataclasses import dataclass, asdict
from pathlib import Path


def terms(text):
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return list(dict.fromkeys(words))


@dataclass
class Memory:
    id: int
    content: str
    memory_type: str
    scope: str
    source: str
    confidence: float
    success: bool
    verify: bool
    created_at: float


class MemoryStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS memories (
              id INTEGER PRIMARY KEY, content TEXT NOT NULL, memory_type TEXT NOT NULL,
              scope TEXT NOT NULL, source TEXT NOT NULL, confidence REAL NOT NULL,
              success INTEGER NOT NULL, verify INTEGER NOT NULL, created_at REAL NOT NULL);
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(content);
        ''')

    def add(self, content, *, memory_type="episodic", scope="", source="user",
            confidence=0.5, success=True, verify=True):
        if memory_type not in {"episodic", "semantic"}:
            raise ValueError("Persist episodic/semantic memory; working memory belongs to TaskState")
        if not content.strip() or not 0 <= confidence <= 1:
            raise ValueError("Memory requires content and confidence in [0,1]")
        with self.db:
            cursor = self.db.execute("INSERT INTO memories VALUES (NULL,?,?,?,?,?,?,?,?)",
                (content, memory_type, scope, source, confidence, int(success), int(verify), time.time()))
            self.db.execute("INSERT INTO memory_fts(rowid,content) VALUES (?,?)",
                            (cursor.lastrowid, " ".join(terms(content))))
        return cursor.lastrowid

    def get(self, id):
        row = self.db.execute("SELECT * FROM memories WHERE id=?", (id,)).fetchone()
        return Memory(**dict(row)) if row else None

    def counts(self):
        return dict(self.db.execute("SELECT memory_type, count(*) FROM memories GROUP BY memory_type"))

    def close(self):
        self.db.close()
