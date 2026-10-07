"""Hooks are optional callbacks, with no registration or plugin lifecycle."""
from dataclasses import dataclass
from typing import Callable
import inspect


@dataclass
class Hooks:
    before_model: Callable | None = None
    after_model: Callable | None = None
    before_tool: Callable | None = None
    after_tool: Callable | None = None
    on_run_end: Callable | None = None

    async def call(self, name: str, *args):
        callback = getattr(self, name)
        if callback:
            value = callback(*args)
            if inspect.isawaitable(value):
                await value
