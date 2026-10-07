"""Five events shared by every OpenAI-compatible endpoint."""
from dataclasses import dataclass, field
from .types import AssistantMessage


@dataclass
class TextDelta:
    delta: str
    type: str = field(default="text_delta", init=False)


@dataclass
class ThinkingDelta:
    delta: str
    type: str = field(default="thinking_delta", init=False)


@dataclass
class ToolCallDelta:
    index: int
    id: str = ""
    name: str = ""
    delta: str = ""
    type: str = field(default="tool_call_delta", init=False)


@dataclass
class Done:
    message: AssistantMessage
    type: str = field(default="done", init=False)


@dataclass
class Error:
    error: str
    type: str = field(default="error", init=False)


StreamEvent = TextDelta | ThinkingDelta | ToolCallDelta | Done | Error
