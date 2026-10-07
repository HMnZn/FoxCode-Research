import argparse
import asyncio
import json
from .config import Config
from .coding_agent import CodingAgent


async def run(config, prompt, json_events=False):
    coding = CodingAgent(config)
    try:
        async for event in coding.run(prompt):
            if json_events:
                print(json.dumps({"type": event.type, "data": event.data}, ensure_ascii=False), flush=True)
            elif event.type == "text_delta":
                print(event.data["delta"], end="", flush=True)
            elif event.type == "tool_start":
                print(f"\n[{event.data['call']['name']}]", flush=True)
            elif event.type == "tool_end":
                print(event.data["result"]["content"], flush=True)
            elif event.type == "error":
                print(f"\nError: {event.data['error']}", flush=True)
            elif event.type == "run_end":
                return 0 if event.data["status"] == "completed" else 1
    finally:
        coding.close()


def main():
    parser = argparse.ArgumentParser(description="FoxCode research coding agent")
    parser.add_argument("prompt")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--model")
    parser.add_argument("--base-url")
    parser.add_argument("--context-budget", type=int)
    parser.add_argument("--json", action="store_true", dest="json_events")
    args = parser.parse_args()
    config = Config.from_env(cwd=args.cwd, model=args.model, base_url=args.base_url,
                             context_budget=args.context_budget)
    raise SystemExit(asyncio.run(run(config, args.prompt, args.json_events)))
