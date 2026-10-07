import asyncio
import sys
import shlex
import os
import subprocess
from pathlib import Path
import pytest
from fox_ai.src import AssistantMessage, Context, Done, Model, TextDelta, ToolCall
from fox_agent_core.src import Agent, Hooks, Read, Write, Edit, Glob, Bash, coding_tools


def python_command(code):
    args = [sys.executable, "-c", code]
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


async def test_five_tools(tmp_path):
    await Write(tmp_path).execute({"file_path": "src/a.py", "content": "one\ntwo\nthree\n"})
    assert "2: two" in await Read(tmp_path).execute({"file_path": "src/a.py", "offset": 2, "limit": 1})
    await Edit(tmp_path).execute({"file_path": "src/a.py", "old_text": "two", "new_text": "four"})
    assert "four" in (tmp_path / "src/a.py").read_text()
    with pytest.raises(ValueError):
        await Edit(tmp_path).execute({"file_path": "src/a.py", "old_text": "missing", "new_text": "x"})
    assert str(Path("src/a.py")) in await Glob(tmp_path).execute({"pattern": "**/*.py"})
    command = python_command("import sys; print(42); print(43, file=sys.stderr)")
    output = await Bash(tmp_path).execute({"command": command})
    assert "returncode: 0" in output and "42" in output and "43" in output


async def test_tool_loop_error_observation_and_hooks(tmp_path):
    calls, seen = [], []
    async def model(model, context, options):
        seen.append(list(context.messages))
        if len(seen) == 1:
            yield Done(AssistantMessage(tool_calls=[ToolCall("a", "Read", {"file_path": "missing"})]))
        elif len(seen) == 2:
            assert context.messages[-1].is_error
            yield Done(AssistantMessage(tool_calls=[ToolCall("b", "Write", {"file_path": "ok", "content": "yes"})]))
        else:
            yield TextDelta("done")
            yield Done(AssistantMessage("done"))
    hooks = Hooks(before_model=lambda c: calls.append("before_model"),
                  after_model=lambda m: calls.append("after_model"),
                  before_tool=lambda c: calls.append("before_tool"),
                  after_tool=lambda c, r: calls.append("after_tool"),
                  on_run_end=lambda s: calls.append(s))
    agent = Agent(Model("fake"), coding_tools(tmp_path), hooks=hooks, stream_fn=model)
    events = [e async for e in agent.run("fix")]
    assert events[-1].data["status"] == "completed"
    assert (tmp_path / "ok").read_text() == "yes"
    assert calls.count("before_model") == 3 and calls.count("after_tool") == 2
    assert calls[-1] == "completed"


async def test_cancel_closes_pending_tool_calls(tmp_path):
    started = asyncio.Event()
    async def model(*args):
        yield Done(AssistantMessage(tool_calls=[ToolCall("a", "Bash", {"command": python_command("import time; time.sleep(30)")})]))
    agent = Agent(Model("fake"), coding_tools(tmp_path), stream_fn=model)
    async def consume():
        events = []
        async for e in agent.run("wait"):
            events.append(e)
            if e.type == "tool_start":
                started.set()
        return events
    task = asyncio.create_task(consume())
    await started.wait()
    await asyncio.sleep(0.1)
    agent.cancel()
    events = await asyncio.wait_for(task, 3)
    assert events[-1].data["status"] == "cancelled"
    assert agent.context.messages[-1].tool_call_id == "a"
    assert agent.context.messages[-1].is_error and not agent.running


async def test_model_cancellation_and_turn_limit():
    started = asyncio.Event()
    async def model(*args):
        started.set()
        await asyncio.sleep(30)
        yield Done(AssistantMessage())
    agent = Agent(Model("fake"), stream_fn=model)
    async def consume():
        return [e async for e in agent.run("hi")]
    task = asyncio.create_task(consume())
    await started.wait()
    agent.cancel()
    assert (await task)[-1].data["status"] == "cancelled"
    agent.max_turns = 0
    events = await consume()
    assert events[-1].data["status"] == "error"
    assert "max_turns" in events[-2].data["error"]


async def test_bash_failure_and_timeout_are_observations(tmp_path):
    with pytest.raises(RuntimeError, match="returncode: 2"):
        await Bash(tmp_path).execute({"command": python_command("import sys; sys.exit(2)")})
    with pytest.raises(TimeoutError):
        await Bash(tmp_path).execute({"command": python_command("import time; time.sleep(30)"), "timeout": 0.1})
