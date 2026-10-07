"""Evidence-gated skill lifecycle and lightweight keyword retrieval."""
import json
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from ..memory.store import terms


@dataclass
class Skill:
    name: str
    description: str
    trigger: str
    instructions: str
    tags: list[str] = field(default_factory=list)
    status: str = "candidate"
    source_trajectory: list[str] = field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    saved_tool_calls: int = 0
    last_used: float = 0
    confidence: float = 0
    version: int = 1
    evidence: list[str] = field(default_factory=list)

    @property
    def utility(self):
        return self.success_count - self.failure_count + self.saved_tool_calls


class SkillStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def save(self, skill):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO skills VALUES (?,?)",
                            (skill.name, json.dumps(asdict(skill), ensure_ascii=False)))
        return skill

    def get(self, name):
        row = self.db.execute("SELECT payload FROM skills WHERE name=?", (name,)).fetchone()
        return Skill(**json.loads(row[0])) if row else None

    def all(self):
        return [Skill(**json.loads(row[0])) for row in self.db.execute("SELECT payload FROM skills ORDER BY name")]

    def propose(self, skill):
        if not all((skill.name, skill.description, skill.trigger, skill.instructions, skill.source_trajectory)):
            raise ValueError("A candidate needs instructions, a trigger and trajectory evidence")
        old = self.get(skill.name)
        if old:
            fresh = [s for s in skill.source_trajectory if s not in old.source_trajectory]
            if fresh:
                old.source_trajectory.extend(fresh)
                # New instructions require new validation; previous evidence is stale.
                if old.instructions != skill.instructions:
                    old.instructions = skill.instructions
                    old.description, old.trigger, old.tags = skill.description, skill.trigger, skill.tags
                    old.version += 1
                    old.status = "candidate"
                    old.evidence = []
                    old.success_count = old.failure_count = old.saved_tool_calls = 0
                    old.confidence = old.last_used = 0
                elif old.status in {"pruned", "rejected"}:
                    old.status = "candidate"
                    old.evidence = []
                    old.success_count = old.failure_count = old.saved_tool_calls = 0
                    old.confidence = old.last_used = 0
            return self.save(old)
        skill.status = "candidate"
        skill.success_count = skill.failure_count = 0
        skill.evidence = []
        return self.save(skill)

    def record(self, name, *, success, evidence_id, saved_calls=0):
        skill = self.get(name)
        if skill is None:
            raise KeyError(name)
        # Replaying a trajectory cannot manufacture validation evidence.
        if evidence_id in skill.evidence:
            return skill
        skill.evidence.append(evidence_id)
        skill.last_used = time.time()
        if success:
            skill.success_count += 1
            skill.saved_tool_calls += max(0, saved_calls)
        else:
            skill.failure_count += 1
        skill.confidence = (skill.success_count + 1) / (skill.success_count + skill.failure_count + 2)
        if skill.failure_count >= 2 and skill.utility <= 0:
            skill.status = "rejected" if skill.status == "candidate" else "pruned"
        elif skill.success_count >= 5 and skill.confidence >= 0.7:
            skill.status = "mature"
        elif skill.success_count >= 2 and skill.confidence >= 0.6:
            skill.status = "active"
        return self.save(skill)

    def retrieve(self, query, top_k=3):
        wanted = set(terms(query))
        scored = []
        for skill in self.all():
            if skill.status not in {"active", "mature"}:
                continue
            keywords = set(terms(" ".join([skill.name, skill.description, skill.trigger, *skill.tags])))
            overlap = len(wanted & keywords)
            if overlap:
                scored.append((overlap + 0.2 * skill.confidence, skill))
        return [skill for _, skill in sorted(scored, key=lambda pair: pair[0], reverse=True)[:top_k]]

    def prune(self, *, now=None, stale_days=90):
        now = time.time() if now is None else now
        for skill in self.all():
            if skill.status in {"active", "mature"} and (skill.utility <= 0 or
                    (skill.last_used and now - skill.last_used > stale_days * 86400 and skill.utility < 3)):
                skill.status = "pruned"
                self.save(skill)

    def close(self):
        self.db.close()


def format_skills(skills):
    return "\n\n".join(f"Skill: {s.name}\nWhen: {s.trigger}\n{s.instructions[:1600]}" for s in skills)
