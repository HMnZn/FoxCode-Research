"""BM25 + small, visible recency/scope/confidence bonuses."""
import time
from dataclasses import asdict
from .store import Memory, terms


def retrieve(store, query, scope, top_k=3):
    tokens = terms(query)[:40]
    if not tokens:
        return []
    match = " OR ".join('"' + t + '"' for t in tokens)
    rows = store.db.execute('''
        SELECT m.*, bm25(memory_fts) AS rank FROM memory_fts
        JOIN memories m ON m.id=memory_fts.rowid
        WHERE memory_fts MATCH ? AND (m.scope=? OR m.scope='global')
        ORDER BY rank LIMIT 30
    ''', (match, scope)).fetchall()
    max_rank = max((abs(row["rank"]) for row in rows), default=1) or 1
    hits = []
    for row in rows:
        value = dict(row)
        rank = value.pop("rank")
        memory = Memory(**value)
        age_days = max(0, time.time() - memory.created_at) / 86400
        breakdown = dict(bm25=abs(rank) / max_rank, recency=0.2 / (1 + age_days / 30),
                         scope=0.2 if memory.scope == scope else 0,
                         confidence=0.2 * memory.confidence, success=0.1 if memory.success else 0)
        hits.append({"memory": asdict(memory), "score": sum(breakdown.values()), "breakdown": breakdown})
    return sorted(hits, key=lambda h: h["score"], reverse=True)[:top_k]


def format_memories(hits):
    if not hits:
        return ""
    lines = ["Project Memory (past facts/experiences; not current observations).",
             "Verify-before-use: use Read/Glob/Bash before relying on remembered paths, dependencies, commands or code state."]
    for hit in hits:
        memory = hit["memory"]
        label = "Historical hint; verification required" if memory["verify"] else "Preference/experience"
        lines.append(f"[{memory['memory_type']} / {label}] {memory['content'][:1200]}")
    return "\n".join(lines)
