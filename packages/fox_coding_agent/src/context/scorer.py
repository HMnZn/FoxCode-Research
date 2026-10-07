"""Explainable utility signals; no trained model is required."""
import re
from dataclasses import dataclass
from fox_ai.src import UserMessage, ToolResultMessage


@dataclass
class Utility:
    recency: float = 0
    task_relevance: float = 0
    dependency_importance: float = 0
    failure_importance: float = 0
    explicit_user_constraint: float = 0

    @property
    def total(self):
        return sum(vars(self).values())


def score(message, index, count, state, seen=None):
    content = message.content
    signals = Utility(recency=2 * (index + 1) / max(1, count))
    terms = set(re.findall(r"\w+", state.goal.lower()))
    signals.task_relevance = min(2, len(terms & set(re.findall(r"\w+", content.lower()))) * 0.25)
    signals.dependency_importance = 2 if any(p in content for p in state.important_files) else 0
    if isinstance(message, UserMessage):
        signals.explicit_user_constraint = 10
    if isinstance(message, ToolResultMessage):
        signals.failure_importance = 4 if message.is_error or re.search(r"Traceback|FAILED|returncode: [1-9]", content) else 0
        if message.name == "Read":
            signals.recency *= 0.5
    if seen is not None and content in seen:
        signals.recency = signals.task_relevance = signals.dependency_importance = 0
    return signals
