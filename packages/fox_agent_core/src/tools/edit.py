from pathlib import Path
from fox_ai.src import Tool


class Edit:
    schema = Tool("Edit", "Replace old_text with new_text; old_text must occur exactly once.", {
        "type": "object", "properties": {"file_path": {"type": "string"},
        "old_text": {"type": "string"}, "new_text": {"type": "string"}},
        "required": ["file_path", "old_text", "new_text"]})

    def __init__(self, cwd):
        self.cwd = Path(cwd)

    async def execute(self, arguments):
        path = self.cwd / arguments["file_path"]
        content = path.read_text(encoding="utf-8")
        old = arguments["old_text"]
        if not old or content.count(old) != 1:
            raise ValueError("old_text must have exactly one non-empty match")
        path.write_text(content.replace(old, arguments["new_text"], 1), encoding="utf-8")
        return f"Edited {arguments['file_path']}"
