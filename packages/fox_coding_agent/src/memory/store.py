"""Versioned project facts and episodes, with evidence separate from repetition."""
import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from ..text import terms


def fingerprint_files(cwd, paths):
    result = {}
    for name in dict.fromkeys(paths):
        path = Path(cwd) / name
        try:
            if path.is_file() and path.stat().st_size <= 1_000_000:
                result[str(name)] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            continue
    return result


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
    key: str = ""
    fingerprint: str = ""
    status: str = "active"
    updated_at: float = 0
    expires_at: float | None = None
    version: int = 1
    supersedes: int | None = None
    metadata: dict = field(default_factory=dict)


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
            CREATE TABLE IF NOT EXISTS memory_evidence (
              memory_id INTEGER NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL,
              observed_at REAL NOT NULL, UNIQUE(memory_id, source, kind));
        ''')
        # Additive migration preserves the user's existing research database.
        columns = {row['name'] for row in self.db.execute('PRAGMA table_info(memories)')}
        definitions = {"key": "TEXT NOT NULL DEFAULT ''", "fingerprint": "TEXT NOT NULL DEFAULT ''",
                       "status": "TEXT NOT NULL DEFAULT 'active'", "updated_at": "REAL NOT NULL DEFAULT 0",
                       "expires_at": "REAL", "version": "INTEGER NOT NULL DEFAULT 1",
                       "supersedes": "INTEGER", "metadata": "TEXT NOT NULL DEFAULT '{}'"}
        with self.db:
            for name, definition in definitions.items():
                if name not in columns:
                    self.db.execute(f'ALTER TABLE memories ADD COLUMN {name} {definition}')
            self.db.execute('CREATE INDEX IF NOT EXISTS memory_scope_key ON memories(scope,key,status)')
            for row in self.db.execute("SELECT id,content FROM memories WHERE fingerprint='' ").fetchall():
                self.db.execute('UPDATE memories SET fingerprint=?,updated_at=created_at WHERE id=?',
                                (self._fingerprint(row['content']), row['id']))

    @staticmethod
    def _fingerprint(content):
        return hashlib.sha256(re.sub(r'\s+', ' ', content.strip()).encode()).hexdigest()

    @staticmethod
    def decode(row):
        value = dict(row)
        value['metadata'] = json.loads(value['metadata'])
        value['success'], value['verify'] = bool(value['success']), bool(value['verify'])
        return Memory(**value)

    def add(self, content, *, memory_type="episodic", scope="", source="user",
            confidence=0.5, success=True, verify=True, key="", ttl_days=None,
            metadata=None, status="active"):
        if memory_type not in {"episodic", "semantic"}:
            raise ValueError("Persist episodic/semantic memory; working memory belongs to TaskState")
        if not content.strip() or not 0 <= confidence <= 1 or (ttl_days is not None and ttl_days <= 0):
            raise ValueError("Memory requires content, confidence in [0,1], and positive TTL")
        if status not in {'active', 'provisional'}:
            raise ValueError('New memory must be active or provisional')
        now, digest = time.time(), self._fingerprint(content)
        with self.db:
            duplicate = self.db.execute('''SELECT id FROM memories WHERE scope=? AND memory_type=?
                AND key=? AND fingerprint=? AND status IN ('active','provisional')''',
                (scope, memory_type, key, digest)).fetchone()
            if duplicate:
                self._evidence(duplicate['id'], source, 'observation', now)
                return duplicate['id']
            previous = self.db.execute('''SELECT id,version FROM memories WHERE scope=? AND key=?
                AND memory_type=? AND status IN ('active','provisional') ORDER BY id DESC LIMIT 1''',
                (scope, key, memory_type)).fetchone() if key else None
            if previous:
                self.db.execute("UPDATE memories SET status='superseded',updated_at=? WHERE id=?", (now, previous['id']))
            cursor = self.db.execute('''INSERT INTO memories
                (content,memory_type,scope,source,confidence,success,verify,created_at,key,fingerprint,
                 status,updated_at,expires_at,version,supersedes,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (content, memory_type, scope, source, confidence, int(success), int(verify), now, key, digest,
                 status, now, now + ttl_days * 86400 if ttl_days else None,
                 previous['version'] + 1 if previous else 1, previous['id'] if previous else None,
                 json.dumps(metadata or {}, ensure_ascii=False)))
            id = cursor.lastrowid
            self.db.execute("INSERT INTO memory_fts(rowid,content) VALUES (?,?)", (id, ' '.join(terms(content))))
            self._evidence(id, source, 'observation', now)
            return id

    def _evidence(self, id, source, kind, now):
        self.db.execute('INSERT OR IGNORE INTO memory_evidence VALUES (?,?,?,?)', (id, source, kind, now))

    def observe_fact(self, key, content, *, scope, source, metadata=None, ttl_days=30):
        """Two independent successful tool trajectories consolidate a provisional fact."""
        id = self.add(content, memory_type='semantic', scope=scope, source=source, key=key,
                      confidence=0.6, metadata=metadata, ttl_days=ttl_days, status='provisional')
        with self.db:
            self._evidence(id, source, 'verified_tool', time.time())
            count = self.db.execute("SELECT count(DISTINCT source) FROM memory_evidence WHERE memory_id=? AND kind='verified_tool'", (id,)).fetchone()[0]
            memory = self.get(id)
            data = {**memory.metadata, **(metadata or {}), 'independent_support': count, 'verified_at': time.time()}
            self.db.execute('UPDATE memories SET status=?,confidence=?,updated_at=?,expires_at=?,metadata=? WHERE id=?',
                            ('active' if count >= 2 else 'provisional', min(0.95, 0.5 + count * 0.15),
                             time.time(), time.time() + ttl_days * 86400, json.dumps(data, ensure_ascii=False), id))
        return id

    def invalidate(self, id, reason):
        memory = self.get(id)
        if not memory:
            raise KeyError(id)
        with self.db:
            self.db.execute("UPDATE memories SET status='invalidated',metadata=?,updated_at=? WHERE id=?",
                            (json.dumps({**memory.metadata, 'invalidated_reason': reason}, ensure_ascii=False), time.time(), id))
        return self.get(id)

    def get(self, id):
        row = self.db.execute('SELECT * FROM memories WHERE id=?', (id,)).fetchone()
        return self.decode(row) if row else None

    def counts(self):
        return dict(self.db.execute("SELECT memory_type,count(*) FROM memories WHERE status IN ('active','provisional') GROUP BY memory_type"))

    def stats(self):
        return {'statuses': dict(self.db.execute('SELECT status,count(*) FROM memories GROUP BY status')),
                'evidence_count': self.db.execute('SELECT count(*) FROM memory_evidence').fetchone()[0]}

    def close(self):
        self.db.close()
