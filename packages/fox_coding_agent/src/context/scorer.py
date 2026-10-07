"""Explainable utility signals; no trained model is required."""
import re
import json
from dataclasses import dataclass
from fox_ai.src import UserMessage, ToolResultMessage
from ..text import terms


@dataclass
class Utility:
    recency: float = 0
    task_relevance: float = 0
    dependency_importance: float = 0
    failure_importance: float = 0
    explicit_user_constraint: float = 0
    novelty: float = 0
    unresolved: float = 0
    stale_penalty: float = 0

    @property
    def total(self):
        return sum(vars(self).values())


def score(message, index, count, state, seen=None):
    content = message.content
    if getattr(message, "tool_calls", None):
        content += json.dumps([c.arguments for c in message.tool_calls], ensure_ascii=False)
    signals = Utility(recency=2 * (index + 1) / max(1, count))
    wanted = set(terms(state.goal))
    signals.task_relevance = min(2, len(wanted & set(terms(content))) * 0.25)
    signals.dependency_importance = 2 if any(p in content for p in state.important_files) else 0
    if isinstance(message, UserMessage):
        signals.explicit_user_constraint = 10
    if isinstance(message, ToolResultMessage):
        signals.failure_importance = 4 if message.is_error or re.search(r"Traceback|FAILED|returncode: [1-9]", content) else 0
        if message.name == "Read":
            signals.recency *= 0.5
            read = state.read_versions.get(message.tool_call_id)
            if read and read["revision"] < state.file_state[read["path"]]["revision"]:
                signals.stale_penalty = -3
        if any(f["call_id"] == message.tool_call_id and f["status"] == "unresolved" for f in state.failure_cases):
            signals.unresolved = 4
    signals.novelty = 0 if not content.strip() else 1
    if seen is not None and content in seen:
        signals.recency = signals.task_relevance = signals.dependency_importance = 0
        signals.novelty = -2
    return signals
