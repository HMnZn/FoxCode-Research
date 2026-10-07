"""FoxCode's OpenAI-compatible model boundary."""
from .types import (Model, Context, StreamOptions, UserMessage, AssistantMessage,
                    ToolResultMessage, TextContent, ToolCall, Tool, Usage, Message)
from .events import TextDelta, ThinkingDelta, ToolCallDelta, Done, Error, StreamEvent
from .stream import stream, complete

__all__ = ["Model", "Context", "StreamOptions", "UserMessage", "AssistantMessage",
           "ToolResultMessage", "TextContent", "ToolCall", "Tool", "Usage", "Message",
           "TextDelta", "ThinkingDelta", "ToolCallDelta", "Done", "Error", "StreamEvent",
           "stream", "complete"]
