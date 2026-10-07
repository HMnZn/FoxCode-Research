"""Research policy is injected through before_model, outside the agent loop."""
from .state import TaskState
from .compressor import compress, estimate_tokens


class ContextManager:
    def __init__(self, budget=12000):
        self.budget = budget
        self.state = TaskState()
        self.summary_message = None
        self.compressions = 0
        self.last = {"tokens": 0, "budget": budget, "compressions": 0}

    def prepare(self, context):
        before = estimate_tokens(context.messages, context.system_prompt, context.tools)
        if before > self.budget:
            raw = [m for m in context.messages if m is not self.summary_message]
            messages, summary, detail = compress(raw, self.state, self.budget,
                                                 context.system_prompt, context.tools)
            context.messages[:] = messages
            self.summary_message = summary
            self.compressions += 1
            self.last = {"before_tokens": before, **detail}
        after = estimate_tokens(context.messages, context.system_prompt, context.tools)
        self.last.update(tokens=after, budget=self.budget, compressions=self.compressions,
                         over_budget=after > self.budget)
        if after > self.budget:
            raise ValueError("Protected goal/constraints and task state exceed context budget; increase context_budget or shorten the prompt")

    def snapshot(self):
        return {**self.last, "state": self.state.snapshot()}
