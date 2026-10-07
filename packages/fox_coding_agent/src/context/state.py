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
        path = call.arguments.get("file_path")
        if path:
            self.add("important_files", path)
        if call.name in {"Write", "Edit"} and not result.is_error:
            self.add("changes", f"{call.name}: {path}")
        command = str(call.arguments.get("command", ""))
        observation = f"{call.name} {path or command}: {result.content[:600]}"
        if result.is_error:
            self.add("failures", observation)
        elif call.name != "Read":
            self.add("observations", observation)
        if call.name == "Bash" and re.search(r"pytest|\btest\b|unittest|tsc|typecheck", command):
            self.add("tests", observation)
        self.working = observation[:500]

    def summary(self):
        labels = {"goal": "Task Goal", "constraints": "Constraints", "plan": "Current Plan",
                  "important_files": "Important Files", "changes": "Changes Made",
                  "observations": "Tool Observations", "failures": "Known Failures",
                  "tests": "Test State", "working": "Current Working State"}
        parts = ["Working Context (structured task state; historical observations require verification)"]
        for key, label in labels.items():
            value = getattr(self, key)
            text = "\n".join(value[-5:]) if isinstance(value, list) else value
            if text:
                parts.append(f"{label}:\n{text[:1200]}")
        return "\n\n".join(parts)

    def snapshot(self):
        return asdict(self)
