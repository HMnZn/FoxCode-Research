from typing import Protocol
from fox_ai.src import Tool, ToolResultMessage


class AgentTool(Protocol):
    schema: Tool

    async def execute(self, arguments: dict) -> str: ...


# All tools return plain text. The loop turns exceptions into observations.
ToolResult = ToolResultMessage
