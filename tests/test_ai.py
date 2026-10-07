from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from fox_ai.src import (AssistantMessage, Context, Done, Error, Model, StreamOptions,
                        ToolCall, ToolResultMessage, UserMessage)
from fox_ai.src.openai_provider import convert_context, stream


def chunk(text=None, reasoning=None, calls=None, finish=None, usage=None):
    return NS(usage=usage, choices=[NS(finish_reason=finish,
              delta=NS(content=text, reasoning_content=reasoning, tool_calls=calls))])


class Response:
    def __init__(self, chunks):
        self.chunks = chunks
        self.close = AsyncMock()

    async def __aiter__(self):
        for value in self.chunks:
            yield value


def client_for(chunks):
    response = Response(chunks)
    return NS(chat=NS(completions=NS(create=AsyncMock(return_value=response)))), response


async def test_text_reasoning_usage_and_request():
    client, response = client_for([chunk(text="hello", reasoning="check"),
                                 chunk(finish="stop", usage=NS(prompt_tokens=10, completion_tokens=3))])
    events = [e async for e in stream(Model("qwen", "http://localhost:8000/v1"),
                                     Context([UserMessage("hi")]), StreamOptions(), client=client)]
    assert [e.type for e in events] == ["text_delta", "thinking_delta", "done"]
    assert events[-1].message.usage.input_tokens == 10
    assert events[-1].message.content == "hello"
    assert client.chat.completions.create.call_args.kwargs["messages"] == [{"role": "user", "content": "hi"}]
    response.close.assert_awaited_once()


async def test_fragmented_multiple_tool_calls_and_conversion():
    def call(index, id=None, name=None, args=None):
        return NS(index=index, id=id, function=NS(name=name, arguments=args))
    client, _ = client_for([
        chunk(calls=[call(1, "b", "Glob", '{"pattern":'), call(0, "a", "Read", '{"file_path":')]),
        chunk(calls=[call(0, args='"a.py"}'), call(1, args='"*.py"}')]), chunk(finish="tool_calls")])
    events = [e async for e in stream(Model("test"), Context(), StreamOptions(), client=client)]
    message = events[-1].message
    assert [c.id for c in message.tool_calls] == ["a", "b"]
    assert message.tool_calls[0].arguments == {"file_path": "a.py"}
    converted = convert_context(Context([message, ToolResultMessage("a", "Read", "source")]))
    assert converted[0]["tool_calls"][0]["function"]["name"] == "Read"
    assert converted[1]["tool_call_id"] == "a"
    assert convert_context(Context([AssistantMessage(reasoning="thought only")])) == []


@pytest.mark.parametrize("chunks", [[chunk(text="partial")], [chunk(calls=[NS(index=0, id="a", function=NS(name="Read", arguments="{"))]), chunk(finish="tool_calls")]])
async def test_incomplete_or_malformed_stream_is_error(chunks):
    client, _ = client_for(chunks)
    events = [e async for e in stream(Model("test"), Context(), StreamOptions(), client=client)]
    assert isinstance(events[-1], Error)
    assert not any(isinstance(e, Done) for e in events)


async def test_request_error():
    client, _ = client_for([])
    client.chat.completions.create.side_effect = RuntimeError("endpoint unavailable")
    events = [e async for e in stream(Model("test"), Context(), StreamOptions(), client=client)]
    assert events == [Error("RuntimeError: endpoint unavailable")]
