"""A thin Chat Completions adapter: conversion, deltas, assembly, usage."""
import json
from openai import AsyncOpenAI
from .events import Done, Error, TextDelta, ThinkingDelta, ToolCallDelta
from .types import AssistantMessage, Context, Model, StreamOptions, ToolCall, Usage


def convert_context(context: Context) -> list[dict]:
    messages = []
    if context.system_prompt:
        messages.append({"role": "system", "content": context.system_prompt})
    for message in context.messages:
        if message.role == "assistant" and not message.content and not message.tool_calls:
            continue
        item = {"role": message.role, "content": message.content}
        if message.role == "tool":
            item["tool_call_id"] = message.tool_call_id
        elif message.role == "assistant":
            if message.reasoning:
                item["reasoning_content"] = message.reasoning
            if message.tool_calls:
                item["tool_calls"] = [
                    {"id": call.id, "type": "function", "function": {
                        "name": call.name, "arguments": json.dumps(call.arguments, ensure_ascii=False)
                    }} for call in message.tool_calls
                ]
        messages.append(item)
    return messages


async def stream(model: Model, context: Context, options: StreamOptions, *, client=None):
    owned = client is None
    response = None
    try:
        client = client or AsyncOpenAI(api_key=options.api_key or "unused",
                                      base_url=model.base_url, timeout=options.timeout,
                                      max_retries=0)
        request = dict(model=model.id, messages=convert_context(context), stream=True,
                       stream_options={"include_usage": True})
        if context.tools:
            request["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters
            }} for t in context.tools]
        if options.temperature is not None:
            request["temperature"] = options.temperature
        if options.max_tokens is not None:
            request["max_tokens"] = options.max_tokens
        if options.extra_body:
            request["extra_body"] = options.extra_body
        response = await client.chat.completions.create(**request)
        message = AssistantMessage()
        calls = {}
        finished = False
        async for chunk in response:
            if chunk.usage:
                message.usage = Usage(chunk.usage.prompt_tokens, chunk.usage.completion_tokens)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.finish_reason:
                message.stop_reason = choice.finish_reason
                finished = True
            delta = choice.delta
            if delta.content:
                message.content += delta.content
                yield TextDelta(delta.content)
            reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
            if reasoning:
                message.reasoning += reasoning
                yield ThinkingDelta(reasoning)
            for part in delta.tool_calls or []:
                call = calls.setdefault(part.index, {"id": "", "name": "", "arguments": ""})
                if part.id:
                    call["id"] = part.id
                if part.function and part.function.name:
                    call["name"] += part.function.name
                fragment = part.function.arguments or "" if part.function else ""
                call["arguments"] += fragment
                yield ToolCallDelta(part.index, call["id"], call["name"], fragment)
        if not finished:
            raise ValueError("Model stream ended without a finish reason")
        for index in sorted(calls):
            raw = calls[index]
            arguments = json.loads(raw["arguments"] or "{}")
            if not isinstance(arguments, dict) or not raw["id"] or not raw["name"]:
                raise ValueError("Invalid streamed tool call")
            message.tool_calls.append(ToolCall(raw["id"], raw["name"], arguments))
        yield Done(message)
    except Exception as exc:
        yield Error(f"{type(exc).__name__}: {exc}")
    finally:
        if response is not None:
            await response.close()
        if owned and client is not None:
            await client.close()
