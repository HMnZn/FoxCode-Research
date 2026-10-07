"""Task state survives raw-history compression, and is distinct from memory."""
import re
from dataclasses import dataclass, field, asdict


@dataclass
class TaskState:
    goal: str = ""
    constraints: list[str] = field(default_factory=list)
    plan: list[str] = field(default_factory=list)
    important_files: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    observations: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    working: str = "Ready"
    file_state: dict = field(default_factory=dict)
    read_versions: dict = field(default_factory=dict)
    failure_cases: list[dict] = field(default_factory=list)
    test_runs: list[dict] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    sequence: int = 0

    def add(self, field_name, text):
        items = getattr(self, field_name)
        if text not in items:
            items.append(text)
        # Raw user messages remain protected separately by ContextManager.
        if field_name != "constraints":
            del items[:-12]

    def user(self, prompt):
        if not self.goal:
            self.goal = prompt[:2000]
        for line in prompt.splitlines():
            if re.search(r"must|never|only|don't|do not|不要|必须|只能|约束|禁止", line, re.I):
                self.add("constraints", line)
        self.working = prompt[:500]

    def assistant(self, message):
        for line in message.content.splitlines():
            if re.match(r"\s*(?:[-*]|\d+[.)])\s", line):
                self.add("plan", line[:300])
        if not message.tool_calls and message.content:
            self.working = message.content[-500:]

    def tool(self, call, result):
        self.sequence += 1
        path = call.arguments.get("file_path")
        if path:
            self.add("important_files", path)
            file = self.file_state.setdefault(path, {"revision": 0, "last_read_revision": None})
            if call.name == "Read" and not result.is_error:
                file.update(last_read_revision=file["revision"], last_read_call=call.id)
                self.read_versions[call.id] = {"path": path, "revision": file["revision"]}
            elif call.name in {"Write", "Edit"} and not result.is_error:
                file["revision"] += 1
                file["last_change_call"] = call.id
        if call.name in {"Write", "Edit"} and not result.is_error:
            self.add("changes", f"{call.name}: {path}")
        command = str(call.arguments.get("command", ""))
        observation = f"{call.name} {path or command}: {result.content[:600]}"
        if result.is_error:
            self.add("failures", observation)
            self.failure_cases.append({"call_id": call.id, "tool": call.name,
                                       "resource": path or command, "error": result.content[:400],
                                       "status": "unresolved", "sequence": self.sequence})
            del self.failure_cases[:-24]
        elif call.name != "Read":
            self.add("observations", observation)
        if not result.is_error:
            for failure in reversed(self.failure_cases):
                if (failure["status"] == "unresolved" and failure["tool"] == call.name
                        and failure["resource"] == (path or command)):
                    failure.update(status="retry_succeeded", recovery_call_id=call.id)
                    break
        if call.name == "Bash" and re.search(r"pytest|\btest\b|unittest|tsc|typecheck", command):
            self.add("tests", observation)
            self.test_runs.append({"call_id": call.id, "command": command,
                                   "outcome": "failed" if result.is_error else "command_succeeded",
                                   "sequence": self.sequence, "output": result.content[:400]})
            del self.test_runs[:-12]
        self.working = observation[:500]

    def summary(self, max_chars=2400):
        labels = {"goal": "Task Goal", "constraints": "Constraints", "plan": "Current Plan",
                  "important_files": "Important Files", "changes": "Changes Made",
                  "observations": "Tool Observations", "failures": "Known Failures",
                  "tests": "Test State", "working": "Current Working State"}
        parts = ["Working Context (structured task state; historical observations require verification)"]
        for key, label in labels.items():
            value = getattr(self, key)
            text = "\n".join(value[-3:]) if isinstance(value, list) else value
            if text:
                parts.append(f"{label}:\n{text[:350]}")
        unresolved = [f["call_id"] for f in self.failure_cases if f["status"] == "unresolved"]
        if unresolved:
            parts.insert(1, "Unresolved evidence: " + ", ".join(unresolved[-6:]))
        stale = [p for p, f in self.file_state.items()
                 if f["last_read_revision"] is not None and f["last_read_revision"] < f["revision"]]
        if stale:
            parts.insert(1, "Changed since last Read; re-read before use: " + ", ".join(stale[-6:]))
        return "\n\n".join(parts)[:max_chars]

    def snapshot(self):
        return asdict(self)
