"""Scope/validity filter -> BM25 -> freshness rerank -> MMR diversification."""
import time
from dataclasses import asdict
from .store import terms, fingerprint_files


def retrieve(store, query, scope, top_k=3, *, cwd=None, now=None):
    tokens = terms(query)[:40]
    if not tokens or top_k <= 0:
        return []
    now = time.time() if now is None else now
    match = ' OR '.join('"' + t + '"' for t in tokens)
    rows = store.db.execute('''
        SELECT m.*, bm25(memory_fts) AS rank FROM memory_fts
        JOIN memories m ON m.id=memory_fts.rowid
        WHERE memory_fts MATCH ? AND (m.scope=? OR m.scope='global') AND m.status='active'
        AND (m.expires_at IS NULL OR m.expires_at>?) ORDER BY rank LIMIT 40
    ''', (match, scope, now)).fetchall()
    max_rank = max((abs(row['rank']) for row in rows), default=1) or 1
    hits = []
    wanted = set(tokens)
    for row in rows:
        value = dict(row)
        rank = value.pop('rank')
        memory = store.decode(value)
        age = max(0, now - (memory.updated_at or memory.created_at)) / 86400
        fingerprints = memory.metadata.get('file_fingerprints', {})
        current = fingerprint_files(cwd, fingerprints) if cwd else {}
        stale_paths = [path for path, digest in fingerprints.items() if cwd and current.get(path) != digest]
        half_life = 90 if memory.memory_type == 'semantic' else 14
        breakdown = dict(bm25=abs(rank) / max_rank, recency=0.2 * 2 ** (-age / half_life),
                         scope=0.2 if memory.scope == scope else 0, confidence=0.2 * memory.confidence,
                         success=0.1 if memory.success else 0,
                         coverage=0.3 * len(wanted & set(terms(memory.content))) / len(wanted),
                         verified=0.1 if memory.metadata.get('independent_support', 0) >= 2 else 0,
                         stale=-0.6 if stale_paths else 0)
        hits.append({'memory': asdict(memory), 'score': sum(breakdown.values()),
                     'breakdown': breakdown, 'stale_paths': stale_paths,
                     'verification': 'stale' if stale_paths else 'required' if memory.verify else 'preference'})
    selected = []
    while hits and len(selected) < top_k:
        for hit in hits:
            own = set(terms(hit['memory']['content']))
            similarities = [len(own & other) / max(1, len(own | other))
                            for other in (set(terms(s['memory']['content'])) for s in selected)]
            hit['diversity_penalty'] = 0.65 * max(similarities, default=0)
            hit['selection_score'] = hit['score'] - hit['diversity_penalty']
        best = max(hits, key=lambda h: (h['selection_score'], -h['memory']['id']))
        selected.append(best)
        hits.remove(best)
    return selected


def format_memories(hits):
    if not hits:
        return ''
    lines = ['Project Memory (past facts/experiences; not current observations).',
             'Verify-before-use: use Read/Glob/Bash before relying on remembered paths, dependencies, commands or code state.']
    for hit in hits:
        memory = hit['memory']
        label = 'Historical hint; verification required' if memory['verify'] else 'Preference/experience'
        if hit.get('stale_paths'):
            label += '; CHANGED files: ' + ', '.join(hit['stale_paths'])
        lines.append(f"[memory:{memory['id']} v{memory.get('version', 1)} / {memory['memory_type']} / {label}] {memory['content'][:1200]}")
    return '\n'.join(lines)
