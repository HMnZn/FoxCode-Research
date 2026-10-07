"""Progressive extractive compression over complete tool-call protocol groups."""
import json
import re
from dataclasses import asdict, replace
from fox_ai.src import AssistantMessage, ToolResultMessage, UserMessage
from .scorer import score


def estimate_tokens(messages, system_prompt="", tools=()):
    # Visible conservative heuristic; ContextManager calibrates using API input usage.
    payload = json.dumps([asdict(m) for m in messages], ensure_ascii=False)
    schemas = json.dumps([asdict(t) for t in tools], ensure_ascii=False)
    return (len((payload + system_prompt + schemas).encode("utf-8")) + 2) // 3


def groups(messages):
    batches = []
    for message in messages:
        if isinstance(message, ToolResultMessage):
            if not batches or not isinstance(batches[-1][0], AssistantMessage):
                raise ValueError("Orphan tool result in context")
            batches[-1].append(message)
        else:
            batches.append([message])
    for batch in batches:
        if isinstance(batch[0], AssistantMessage):
            calls = [c.id for c in batch[0].tool_calls]
            results = [m.tool_call_id for m in batch[1:]]
            if len(calls) != len(set(calls)) or sorted(calls) != sorted(results):
                raise ValueError("Context contains incomplete/duplicate tool-call results")
    return batches


def compact_observation(message, state, limit=1000):
    """Keep head, diagnostic lines and tail; archive references preserve provenance."""
    if len(message.content) <= limit:
        return message
    diagnostics = [line[:220] for line in message.content.splitlines()
                   if re.search(r"error|failed|traceback|exception|passed|returncode|assert", line, re.I)]
    reference = state.artifacts.get(message.tool_call_id, "trajectory tool_call_id=" + message.tool_call_id)
    header = f"[Compacted historical observation; full evidence: {reference}]\n"
    room = max(0, limit - len(header) - 60)
    chunks = [message.content[:room // 3], "\n...\n",
              "\n".join(dict.fromkeys(diagnostics))[:room // 3], "\n...\n", message.content[-room // 3:]]
    return replace(message, content=header + "".join(chunks))


def compress(messages, state, budget, system_prompt="", tools=()):
    batches = groups(messages)
    summary = UserMessage(state.summary(max_chars=min(2400, max(300, budget))))
    selected = {i for i, batch in enumerate(batches) if isinstance(batch[0], UserMessage)}
    variants, utilities, breakdowns, seen = {}, {}, {}, set()
    for i, batch in enumerate(batches):
        signals = [score(m, i, len(batches), state, seen) for m in batch]
        utilities[i] = max((s.total for s in signals), default=0)
        breakdowns[i] = [asdict(s) for s in signals]
        variants[i] = [compact_observation(m, state) if isinstance(m, ToolResultMessage)
                       else replace(m, reasoning="") if isinstance(m, AssistantMessage) else m for m in batch]
        seen.update(m.content for m in batch if m.content)

    def build(indices):
        return [summary] + [m for i in sorted(indices) for m in variants[i]]

    def fits(indices):
        return estimate_tokens(build(indices), system_prompt, tools) <= budget

    if not fits(selected):
        summary.content = state.summary(max_chars=300)
    # Latest non-user group is a continuity anchor. Never drop it silently.
    recent = [i for i, batch in enumerate(batches) if not isinstance(batch[0], UserMessage)][-3:]
    if recent:
        selected.add(recent[-1])
    for i in reversed(recent[:-1]):
        if fits(selected | {i}):
            selected.add(i)
    older = [i for i in range(len(batches)) if i not in selected]
    older.sort(key=lambda i: utilities[i] / max(1, estimate_tokens(variants[i])), reverse=True)
    for i in older:
        if utilities[i] >= 3 and fits(selected | {i}):
            selected.add(i)
    output = {i: variants[i] for i in selected}
    # Restore raw observations when spare capacity remains, newest first.
    for i in sorted(selected, reverse=True):
        candidate = [summary] + [m for j in sorted(selected) for m in (batches[j] if j == i else output[j])]
        if estimate_tokens(candidate, system_prompt, tools) <= budget:
            output[i] = batches[i]
    decisions = []
    for i, batch in enumerate(batches):
        action = "drop" if i not in selected else "raw" if output[i] == batch else "compact"
        decisions.append({"group": i, "action": action, "utility": round(utilities[i], 3),
                          "tokens": estimate_tokens(batch),
                          "signals": breakdowns[i],
                          "reason": "protected_user" if isinstance(batch[0], UserMessage)
                          else "latest_observation" if recent and i == recent[-1] else "utility_per_token"})
    messages = [summary] + [m for i in sorted(selected) for m in output[i]]
    return messages, summary, {"kept_groups": len(selected), "dropped_groups": len(batches) - len(selected),
                              "compacted_groups": sum(d["action"] == "compact" for d in decisions),
                              "decisions": decisions,
                              "utility": {str(i): round(s, 2) for i, s in utilities.items()}}
