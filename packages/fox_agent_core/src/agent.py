"""Small stateful facade over the readable agent loop."""
import asyncio
from fox_ai.src import Context, StreamOptions, UserMessage, stream
from .agent_loop import agent_loop
from .events import AgentEvent
from .hooks import Hooks


class Agent:
    def __init__(self, model, tools=(), *, system_prompt="", options=None,
                 hooks=None, stream_fn=stream, max_turns=30):
        self.model = model
        self.tools = {t.schema.name: t for t in tools}
        if len(self.tools) != len(tools):
            raise ValueError("Tool names must be unique")
        self.context = Context(system_prompt=system_prompt, tools=[t.schema for t in tools])
        self.options = options or StreamOptions()
        self.hooks = hooks or Hooks()
        self.stream_fn = stream_fn
        self.max_turns = max_turns
        self._task = None

    @property
    def running(self):
        return self._task is not None

    def cancel(self):
        if self._task:
            self._task.cancel()

    async def run(self, prompt: str):
        if self.running:
            raise RuntimeError("Agent is already running")
        self._task = asyncio.current_task()
        self.context.messages.append(UserMessage(prompt))
        status = "completed"
        try:
            yield AgentEvent("run_start")
            async for event in agent_loop(self.model, self.context, self.options, self.tools,
                                          self.hooks, self.stream_fn, self.max_turns):
                yield event
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception as exc:
            status = "error"
            yield AgentEvent("error", {"error": str(exc)})
        finally:
            self._task = None
        yield AgentEvent("run_end", {"status": status})
