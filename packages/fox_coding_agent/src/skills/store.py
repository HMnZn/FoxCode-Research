"""Versioned candidates, stable serving versions, and externally supplied feedback."""
import json
import math
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from ..text import terms


@dataclass
class Skill:
    name: str
    description: str
    trigger: str
    instructions: str
    tags: list[str] = field(default_factory=list)
    status: str = 'candidate'
    source_trajectory: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    saved_tool_calls: int = 0
    last_used: float = 0
    confidence: float = 0
    version: int = 1
    evidence: list[str] = field(default_factory=list)
    scope: str = ''
    environment: dict = field(default_factory=dict)
    preconditions: list[str] = field(default_factory=list)
    procedure: list[str] = field(default_factory=list)
    verification: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    experiences: list[dict] = field(default_factory=list)
    family: str = ''
    created_at: float = field(default_factory=time.time)
    retrieved_count: int = 0
    injected_count: int = 0
    champion_version: int | None = None

    @property
    def utility(self):
        # Reported call savings are bounded on ingestion; they are not measured here.
        return self.success_count - 2 * self.failure_count + self.saved_tool_calls

    @property
    def confidence_lower(self):
        n = self.success_count + self.failure_count
        if not n:
            return 0.0
        p, z = self.success_count / n, 1.96
        return (p + z*z/(2*n) - z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / (1 + z*z/n)


class SkillStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS skill_versions(
              name TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(name,version));
            CREATE TABLE IF NOT EXISTS skill_champions(name TEXT PRIMARY KEY, version INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS skill_events(
              id INTEGER PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL, action TEXT NOT NULL,
              reason TEXT NOT NULL, source TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS skill_usage(
              name TEXT NOT NULL, version INTEGER NOT NULL, trajectory TEXT NOT NULL,
              stage TEXT NOT NULL, UNIQUE(name,version,trajectory,stage));
            CREATE TABLE IF NOT EXISTS evolution_pending(scope TEXT PRIMARY KEY, payload TEXT NOT NULL);
        ''')
        self.last_retrieval = []
        with self.db:
            for name, payload in self.db.execute('SELECT name,payload FROM skills').fetchall():
                skill = Skill(**json.loads(payload))
                self.db.execute('INSERT OR IGNORE INTO skill_versions VALUES (?,?,?)', (name, skill.version, payload))
                if skill.status in {'active', 'mature'}:
                    self.db.execute('INSERT OR IGNORE INTO skill_champions VALUES (?,?)', (name, skill.version))

    def _decode(self, payload):
        skill = Skill(**json.loads(payload))
        row = self.db.execute('SELECT version FROM skill_champions WHERE name=?', (skill.name,)).fetchone()
        skill.champion_version = row[0] if row else None
        return skill

    def event(self, name, version, action, reason, source=''):
        self.db.execute('INSERT INTO skill_events VALUES (NULL,?,?,?,?,?,?)',
                        (name, version, action, reason, source, time.time()))

    @staticmethod
    def _policy(skill):
        fields = ('description', 'trigger', 'instructions', 'tags', 'scope', 'environment',
                  'preconditions', 'procedure', 'verification', 'anti_patterns', 'family')
        return {key: getattr(skill, key) for key in fields}

    def _save(self, skill, *, action='', reason='', source=''):
        """Write within the caller's transaction, including audit events."""
        payload = json.dumps(asdict(skill), ensure_ascii=False)
        previous = self.get(skill.name, skill.version)
        if previous and self._policy(previous) != self._policy(skill):
            raise ValueError('Policy content is immutable within a skill version')
        self.db.execute('INSERT OR REPLACE INTO skill_versions VALUES (?,?,?)', (skill.name, skill.version, payload))
        current = self.get(skill.name)
        if current is None or current.version <= skill.version:
            self.db.execute('INSERT OR REPLACE INTO skills VALUES (?,?)', (skill.name, payload))
        if action:
            self.event(skill.name, skill.version, action, reason, source)

    def save(self, skill, *, action='', reason='', source=''):
        with self.db:
            self._save(skill, action=action, reason=reason, source=source)
        return self.get(skill.name, skill.version)

    def get(self, name, version=None):
        row = self.db.execute('SELECT payload FROM skills WHERE name=?', (name,)).fetchone() if version is None else self.db.execute(
            'SELECT payload FROM skill_versions WHERE name=? AND version=?', (name, version)).fetchone()
        return self._decode(row[0]) if row else None

    def all(self):
        return [self._decode(row[0]) for row in self.db.execute('SELECT payload FROM skills ORDER BY name').fetchall()]

    def serving(self, name):
        row = self.db.execute('SELECT version FROM skill_champions WHERE name=?', (name,)).fetchone()
        skill = self.get(name, row[0]) if row else None
        return skill if skill and skill.status in {'active', 'mature'} else None

    def propose(self, skill):
        if not all((skill.name, skill.description, skill.trigger, skill.instructions, skill.source_trajectory)):
            raise ValueError('A candidate needs instructions, a trigger and trajectory evidence')
        old = self.get(skill.name)
        if old and self._policy(old) == self._policy(skill) and old.status not in {'pruned', 'rejected'}:
            old.source_trajectory = list(dict.fromkeys(old.source_trajectory + skill.source_trajectory))
            known = {json.dumps(e, sort_keys=True) for e in old.experiences}
            old.experiences.extend(e for e in skill.experiences if json.dumps(e, sort_keys=True) not in known)
            return self.save(old, action='merge_evidence', reason='Identical procedure; no extra validation credit', source=skill.source_trajectory[-1])
        skill.version = old.version + 1 if old else 1
        skill.status = 'candidate'
        skill.success_count = skill.failure_count = skill.saved_tool_calls = 0
        skill.retrieved_count = skill.injected_count = 0
        skill.confidence = skill.last_used = 0
        skill.evidence = []
        skill.created_at = time.time()
        if old:
            skill.source_trajectory = list(dict.fromkeys(old.source_trajectory + skill.source_trajectory))
        return self.save(skill, action='revise' if old else 'add',
                         reason='New candidate; serving version remains unchanged', source=skill.source_trajectory[-1])

    def record(self, name, *, success, evidence_id, saved_calls=0, version=None):
        skill = self.get(name, version)
        if skill is None:
            raise KeyError(name)
        if evidence_id in skill.evidence:
            return skill
        if evidence_id in skill.source_trajectory:
            raise ValueError('Validate on a held-out trajectory, not the extraction source')
        if skill.status in {'pruned', 'rejected'}:
            raise ValueError('Archived skill versions require a new candidate revision')
        skill.evidence.append(evidence_id)
        skill.last_used = time.time()
        if success:
            skill.success_count += 1
            skill.saved_tool_calls += min(5, max(0, saved_calls))
        else:
            skill.failure_count += 1
        skill.confidence = (skill.success_count + 1) / (skill.success_count + skill.failure_count + 2)
        if skill.failure_count >= 2 and skill.utility <= 0:
            skill.status = 'rejected' if skill.status == 'candidate' else 'pruned'
        elif skill.success_count >= 5 and skill.confidence >= 0.7:
            skill.status = 'mature'
        elif skill.success_count >= 2 and skill.confidence >= 0.6:
            skill.status = 'active'
        else:
            skill.status = 'candidate'
        with self.db:
            self._save(skill, action='feedback', reason='useful' if success else 'not_useful', source=evidence_id)
            if skill.status in {'active', 'mature'}:
                # Never replace a newer approved revision with late old-version feedback.
                champion = self.serving(name)
                if champion is None or skill.version > champion.version:
                    self.db.execute('INSERT OR REPLACE INTO skill_champions VALUES (?,?)', (name, skill.version))
                    self.event(name, skill.version, 'promote', 'External feedback gate satisfied', evidence_id)
            elif skill.champion_version == skill.version:
                self.db.execute('DELETE FROM skill_champions WHERE name=?', (name,))
        return self.get(name, skill.version)

    def mark_usage(self, name, version, trajectory, stage):
        if stage not in {'retrieved', 'injected'}:
            raise ValueError('Retrieval/injection do not imply adoption; feedback is separate')
        skill = self.get(name, version)
        if not skill:
            raise KeyError(name)
        with self.db:
            cursor = self.db.execute('INSERT OR IGNORE INTO skill_usage VALUES (?,?,?,?)', (name, version, trajectory, stage))
            if cursor.rowcount:
                field = 'retrieved_count' if stage == 'retrieved' else 'injected_count'
                setattr(skill, field, getattr(skill, field) + 1)
                self._save(skill)

    def retrieve(self, query, top_k=3, *, scope='', environment=None):
        wanted = set(terms(query))
        documents = []
        for current in self.all():
            skill = self.serving(current.name)
            if not skill or (skill.scope and skill.scope != scope):
                continue
            if any((environment or {}).get(k) != v for k, v in skill.environment.items()):
                continue
            tf = Counter()
            for text, weight in [(skill.trigger, 2), (skill.description, 1.5),
                                 (' '.join([skill.name, *skill.tags]), 2), (skill.instructions[:1200], 0.4)]:
                for token in terms(text):
                    tf[token] += weight
            documents.append((skill, tf))
        df = Counter(token for _, tf in documents for token in tf)
        average = sum(sum(tf.values()) for _, tf in documents) / max(1, len(documents))
        scored = []
        for skill, tf in documents:
            lexical = 0
            for token in wanted & tf.keys():
                idf = math.log(1 + (len(documents) - df[token] + 0.5) / (df[token] + 0.5))
                lexical += idf * tf[token] * 2.2 / (tf[token] + 1.2 * (0.25 + 0.75 * sum(tf.values()) / max(1, average)))
            if lexical:
                scored.append((lexical + 0.2 * skill.confidence_lower, skill))
        scored.sort(key=lambda pair: (-pair[0], pair[1].name))
        self.last_retrieval = [{'name': s.name, 'version': s.version, 'score': round(score, 4),
                               'confidence_lower': round(s.confidence_lower, 4)} for score, s in scored]
        selected, families = [], set()
        for _, skill in scored:
            family = skill.family or skill.name
            if family not in families and len(selected) < top_k:
                selected.append(skill)
                families.add(family)
        return selected

    def rollback(self, name, version, *, reason):
        skill = self.get(name, version)
        if not skill or skill.status not in {'active', 'mature'}:
            raise ValueError('Rollback requires a previously validated active/mature version')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO skill_champions VALUES (?,?)', (name, version))
            self.event(name, version, 'rollback', reason)
        return self.get(name, version)

    def history(self, name):
        versions = [self._decode(row[0]) for row in self.db.execute(
            'SELECT payload FROM skill_versions WHERE name=? ORDER BY version', (name,)).fetchall()]
        events = [dict(zip(('version', 'action', 'reason', 'source', 'created_at'), row)) for row in self.db.execute(
            'SELECT version,action,reason,source,created_at FROM skill_events WHERE name=? ORDER BY id', (name,)).fetchall()]
        return {'versions': [asdict(s) for s in versions], 'events': events}

    def prune(self, *, now=None, stale_days=90):
        now = time.time() if now is None else now
        for current in self.all():
            skill = self.serving(current.name)
            if skill and (skill.utility <= 0 or (skill.last_used and now - skill.last_used > stale_days * 86400 and skill.utility < 3)):
                skill.status = 'pruned'
                with self.db:
                    self._save(skill, action='prune', reason='Low utility or stale weak evidence')
                    self.db.execute('DELETE FROM skill_champions WHERE name=?', (skill.name,))

    def close(self):
        self.db.close()


def format_skills(skills):
    blocks = []
    for skill in skills:
        parts = [f'Skill: {skill.name} v{skill.version} ({skill.status})', f'When: {skill.trigger}']
        if skill.preconditions:
            parts.append('Preconditions: ' + '; '.join(skill.preconditions))
        parts.append(skill.instructions[:1600])
        if skill.verification:
            parts.append('Verify: ' + '; '.join(skill.verification))
        if skill.anti_patterns:
            parts.append('Avoid: ' + '; '.join(skill.anti_patterns))
        blocks.append('\n'.join(parts))
    return '\n\n'.join(blocks)
