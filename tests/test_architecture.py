"""A useful regression guard: lower layers cannot acquire project policy again."""
import ast
from pathlib import Path


def test_dependency_direction_and_small_model_surface():
    root = Path(__file__).resolve().parents[1] / "packages"
    assert {p.stem for p in (root / "fox_ai/src").glob("*.py")} == {
        "__init__", "types", "events", "stream", "openai_provider"}
    for package in ["fox_ai", "fox_agent_core"]:
        for path in (root / package / "src").rglob("*.py"):
            imports = []
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
            assert not any(name.startswith("fox_coding_agent") for name in imports), path
            if package == "fox_ai":
                assert not any(name.startswith("fox_agent_core") for name in imports), path
    assert not (root / "fox_agent_core/src/harness").exists()
    assert not (root / "fox_coding_agent/src/core").exists()
