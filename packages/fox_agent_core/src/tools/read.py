import asyncio
from pathlib import Path
from fox_ai.src import Tool


class Read:
    schema = Tool("Read", "Read numbered text lines; offset is 1-based, limit defaults to 200.", {
        "type": "object", "properties": {"file_path": {"type": "string"},
        "offset": {"type": "integer", "minimum": 1}, "limit": {"type": "integer", "minimum": 1}},
        "required": ["file_path"]})

    def __init__(self, cwd):
        self.cwd = Path(cwd)

    async def execute(self, arguments):
        return await asyncio.to_thread(self._read, arguments)

    def _read(self, arguments):
        start, limit = int(arguments.get("offset", 1)), int(arguments.get("limit", 200))
        if start < 1 or limit < 1:
            raise ValueError("offset and limit must be positive")
        output, size = [], 0
        with (self.cwd / arguments["file_path"]).open(encoding="utf-8") as file:
            for number, line in enumerate(file, 1):
                if number < start:
                    continue
                text = f"{number}: {line.rstrip()}"
                output.append(text[:max(0, 20000 - size)])
                size += len(text) + 1
                if number >= start + limit - 1 or size >= 20000:
                    output.append("[output limited; use offset/limit for more]")
                    break
        return "\n".join(output)
