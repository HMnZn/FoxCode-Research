"""Shared deterministic English/code tokens and Chinese bigrams."""
import re


def terms(text):
    words = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(run[i:i + 2] for i in range(max(1, len(run) - 1)))
    return list(dict.fromkeys(words))
