"""Model -> tool calls -> observations -> model. No project policy lives here."""
import asyncio
from dataclasses import asdict
from fox_ai.src import Done, Error, ToolResultMessage
from .events import AgentEvent


async def agent_loop(model, context, options, tools, hooks, stream_fn, max_turns):
    status = "error"
    try:
        for turn in range(max_turns):
            await hooks.call("before_model", context)
            yield AgentEvent("model_start", {"turn": turn})
            message = None
            async for event in stream_fn(model, context, options):
                if isinstance(event, Error):
                    raise RuntimeError(event.error)
                if isinstance(event, Done):
                    message = event.message
                else:
                    payload = asdict(event)
                    payload.pop("type")
                    yield AgentEvent(event.type, payload)
            if message is None:
                raise RuntimeError("Model stream returned no message")
            # Truncated calls must never execute partially generated writes.
            if message.stop_reason in {"length", "content_filter"}:
                raise RuntimeError(f"Model stopped with {message.stop_reason}")
            context.messages.append(message)
            await hooks.call("after_model", message)
            yield AgentEvent("model_end", {"message": asdict(message)})
            if not message.tool_calls:
                status = "completed"
                return
            pending = list(message.tool_calls)
            try:
                for call in message.tool_calls:
                    yield AgentEvent("tool_start", {"call": asdict(call)})
                    try:
                        await hooks.call("before_tool", call)
                        tool = tools.get(call.name)
                        if tool is None:
                            raise ValueError(f"Unknown tool: {call.name}")
                        output = await tool.execute(call.arguments)
                        result = ToolResultMessage(call.id, call.name, output)
                    except Exception as exc:
                        result = ToolResultMessage(call.id, call.name, f"{type(exc).__name__}: {exc}", True)
                    context.messages.append(result)
                    pending.pop(0)
                    await hooks.call("after_tool", call, result)
                    yield AgentEvent("tool_end", {"call": asdict(call), "result": asdict(result)})
            finally:
                # Keep the OpenAI call/result pairing valid after interruption.
                for call in pending:
                    context.messages.append(ToolResultMessage(call.id, call.name, "Execution interrupted", True))
        raise RuntimeError(f"Agent reached max_turns={max_turns}")
    except asyncio.CancelledError:
        status = "cancelled"
        raise
    finally:
        await hooks.call("on_run_end", status)
