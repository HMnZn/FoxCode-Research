"""Allocate prompt layers, calibrate estimates, and compress with hysteresis."""
from fox_ai.src import UserMessage
from .state import TaskState
from .compressor import compress, estimate_tokens


class ContextManager:
    def __init__(self, budget=12000, *, context_window=None, max_tokens=4096):
        self.budget = min(budget, context_window - max_tokens) if context_window else budget
        self.state = TaskState()
        self.summary_message = None
        self.compressions = 0
        self.calibration = 1.0
        self.last_estimate = 0
        self.base_prompt = None
        self.blocks = []
        self.history = []
        self.last = {"tokens": 0, "budget": self.budget, "compressions": 0}

    def set_sources(self, base_prompt, blocks):
        """Blocks are {kind,id,text,score,required?}; policy stays outside the harness."""
        self.base_prompt, self.blocks = base_prompt, blocks

    def observe_usage(self, usage):
        if usage.input_tokens > 0 and self.last_estimate > 0:
            ratio = min(3.0, max(0.5, usage.input_tokens / self.last_estimate))
            self.calibration = max(1.0, 0.8 * self.calibration + 0.2 * ratio)
            self.last["actual_input_tokens"] = usage.input_tokens

    def prepare(self, context):
        raw_budget = int(self.budget / self.calibration)
        raw = [m for m in context.messages if m is not self.summary_message]
        if self.base_prompt is not None:
            protected = [m for m in raw if isinstance(m, UserMessage)]
            room = max(0, min(int(raw_budget * 0.25), raw_budget -
                             estimate_tokens(protected, self.base_prompt, context.tools) - 400))
            prompt, selected, dropped = self.base_prompt, [], []
            spent = 0
            for block in sorted(self.blocks, key=lambda b: (bool(b.get("required")), b.get("score", 0)), reverse=True):
                cost = estimate_tokens([], block["text"]) - estimate_tokens([])
                if spent + cost > room:
                    if block.get("required"):
                        raise ValueError("Explicit trial skill exceeds retrieval budget; increase context_budget")
                    dropped.append({"kind": block["kind"], "id": block["id"]})
                    continue
                prompt += "\n\n" + block["text"]
                spent += cost
                selected.append({"kind": block["kind"], "id": block["id"]})
            context.system_prompt = prompt
            self.last.update(retrieval_selected=selected, retrieval_dropped=dropped)
        before = estimate_tokens(context.messages, context.system_prompt, context.tools)
        if before > int(raw_budget * 0.9):
            target = int(raw_budget * 0.75)
            messages, summary, detail = compress(raw, self.state, target, context.system_prompt, context.tools)
            if estimate_tokens(messages, context.system_prompt, context.tools) > target:
                messages, summary, detail = compress(raw, self.state, raw_budget, context.system_prompt, context.tools)
            context.messages[:] = messages
            self.summary_message = summary
            self.compressions += 1
            self.last.update(before_tokens=round(before * self.calibration), target_tokens=target, **detail)
        after = estimate_tokens(context.messages, context.system_prompt, context.tools)
        self.last_estimate = after
        self.last.update(tokens=round(after * self.calibration), budget=self.budget,
                         compressions=self.compressions, calibration=round(self.calibration, 3),
                         over_budget=after > raw_budget,
                         layers={"system_and_retrieval": estimate_tokens([], context.system_prompt),
                                 "tools": estimate_tokens([], tools=context.tools),
                                 "history": estimate_tokens(context.messages)})
        self.history.append({k: self.last[k] for k in ("tokens", "budget", "compressions", "calibration")})
        del self.history[:-30]
        if after > raw_budget:
            raise ValueError("Protected goal/constraints, latest observation and tool schemas exceed context budget; increase context_budget or shorten the prompt")

    def snapshot(self):
        return {**self.last, "state": self.state.snapshot(), "history": list(self.history)}
