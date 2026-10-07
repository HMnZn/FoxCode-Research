from pathlib import Path
from fox_ai.src import Tool


class Glob:
    schema = Tool("Glob", "Discover files/directories by glob pattern (up to 500 results).", {
        "type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}},
        "required": ["pattern"]})

    def __init__(self, cwd):
        self.cwd = Path(cwd)

    async def execute(self, arguments):
        root = self.cwd / arguments.get("path", ".")
        results = []
        for path in root.glob(arguments["pattern"]):
            results.append(str(path.relative_to(root)))
            if len(results) == 500:
                break
        return "\n".join(sorted(results)) or "No matches"
