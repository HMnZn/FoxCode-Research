"""Select whole protocol groups, retaining user constraints and recent raw turns."""
import json
from dataclasses import asdict
from fox_ai.src import AssistantMessage, UserMessage
from .scorer import score


def estimate_tokens(messages, system_prompt="", tools=()):
    # UTF-8 bytes/3 is a conservative heuristic, not the endpoint's tokenizer.
    payload = json.dumps([asdict(m) for m in messages], ensure_ascii=False)
    schemas = json.dumps([asdict(t) for t in tools], ensure_ascii=False)
    return (len((payload + system_prompt + schemas).encode("utf-8")) + 2) // 3


def groups(messages):
    result = []
    for message in messages:
        if message.role == "tool" and result and isinstance(result[-1][0], AssistantMessage):
            result[-1].append(message)
        else:
            result.append([message])
    return result


def compress(messages, state, budget, system_prompt="", tools=()):
    batches = groups(messages)
    summary = UserMessage(state.summary())
    # Every genuine user message is protected, without truncating constraints.
    selected = {i for i, group in enumerate(batches) if isinstance(group[0], UserMessage)}
    scores, seen = {}, set()
    for i, group in enumerate(batches):
        scores[i] = max(score(m, i, len(batches), state, seen).total for m in group)
        seen.update(m.content for m in group)
    def build(indices):
        return [summary] + [m for i, batch in enumerate(batches) if i in indices for m in batch]
    # Recent raw context is selected first; then high-utility older groups.
    recent = list(range(max(0, len(batches) - 3), len(batches)))
    older = sorted((i for i in range(len(batches)) if i not in recent),
                   key=lambda i: scores[i], reverse=True)
    for i in reversed(recent):
        if estimate_tokens(build(selected | {i}), system_prompt, tools) <= budget:
            selected.add(i)
    for i in older:
        if scores[i] >= 3 and estimate_tokens(build(selected | {i}), system_prompt, tools) <= budget:
            selected.add(i)
    return build(selected), summary, {"kept_groups": len(selected), "dropped_groups": len(batches) - len(selected),
                                      "utility": {str(i): round(s, 2) for i, s in scores.items()}}
