from pathlib import Path
from fox_ai.src import Tool


class Write:
    schema = Tool("Write", "Create or overwrite a UTF-8 text file.", {
        "type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}},
        "required": ["file_path", "content"]})

    def __init__(self, cwd):
        self.cwd = Path(cwd)

    async def execute(self, arguments):
        path = self.cwd / arguments["file_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(arguments["content"], encoding="utf-8")
        return f"Wrote {arguments['file_path']}"
