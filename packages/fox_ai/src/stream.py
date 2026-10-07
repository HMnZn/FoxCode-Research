"""Convenience entry point for non-streaming callers."""
from .openai_provider import stream
from .events import Done, Error
from .types import Context, Model, StreamOptions


async def complete(model: Model, context: Context, options: StreamOptions):
    async for event in stream(model, context, options):
        if isinstance(event, Error):
            raise RuntimeError(event.error)
        if isinstance(event, Done):
            return event.message
    raise RuntimeError("Model stream returned no final message")
