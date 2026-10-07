"""The complete model boundary: messages, tools and request options."""
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Model:
    id: str
    base_url: str = "https://api.openai.com/v1"
    context_window: int = 32768


@dataclass
class TextContent:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class UserMessage:
    content: str
    role: Literal["user"] = field(default="user", init=False)


@dataclass
class AssistantMessage:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str = ""
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = "stop"
    role: Literal["assistant"] = field(default="assistant", init=False)


@dataclass
class ToolResultMessage:
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False
    role: Literal["tool"] = field(default="tool", init=False)


Message = UserMessage | AssistantMessage | ToolResultMessage


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict


@dataclass
class Context:
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    tools: list[Tool] = field(default_factory=list)


@dataclass
class StreamOptions:
    api_key: str = field(default="", repr=False)
    temperature: float | None = None
    max_tokens: int | None = None
    timeout: float = 120
    # Explicit endpoint escape hatch; there are no vendor-specific classes.
    extra_body: dict = field(default_factory=dict)
