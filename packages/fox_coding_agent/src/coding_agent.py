"""Compose the harness with FoxCode's three research policies."""
import json
import re
import time
import uuid
import hashlib
import sys
import os
from dataclasses import asdict
from fox_ai.src import stream
from fox_agent_core.src import Agent, AgentEvent, Hooks, coding_tools
from .context import ContextManager
from .memory import MemoryStore, retrieve, format_memories
from .memory.store import fingerprint_files
from .skills import SkillStore, SkillEvolution, format_skills


SYSTEM_PROMPT = """You are FoxCode, a coding agent working in a project directory.
Inspect files, make focused changes and validate with available tools.
Read/Write/Edit paths and Bash cwd are relative to the project directory.
Treat retrieved memory and skill examples as historical hints. Verify paths,
dependencies, commands and code state with Read/Glob/Bash before relying on them.
When a tool fails, inspect the cause before retrying. Give a concise final report.
"""


class CodingAgent:
    def __init__(self, config, *, stream_fn=stream):
        self.config = config
        config.data_dir.mkdir(parents=True, exist_ok=True)
        self.scope = str(config.cwd)
        self.context = ContextManager(config.context_budget, context_window=config.context_window,
                                      max_tokens=config.max_tokens)
        self.memory = MemoryStore(config.data_dir / "memory.sqlite")
        self.skills = SkillStore(config.data_dir / "skills.sqlite")
        self.evolution = SkillEvolution(self.skills)
        self.memory_hits = []
        self.selected_skills = []
        self.trajectory = None
        self._running = False
        hooks = Hooks(before_model=self._before_model, after_model=self._after_model,
                      before_tool=self._before_tool, after_tool=self._after_tool)
        self.agent = Agent(config.model_config(), coding_tools(config.cwd),
                           options=config.stream_options(), hooks=hooks, stream_fn=stream_fn,
                           max_turns=config.max_turns)

    @property
    def running(self):
        return self._running

    def _after_model(self, message):
        self.context.observe_usage(message.usage)
        self.context.state.assistant(message)
        self.trajectory["messages"].append(asdict(message))

    def _before_model(self, context):
        self.context.prepare(context)
        self.trajectory["context_calls"].append({"tokens": self.context.last["tokens"],
                                               "retrieval_selected": self.context.last.get("retrieval_selected", []),
                                               "retrieval_dropped": self.context.last.get("retrieval_dropped", [])})
        injected = {b["id"] for b in self.context.last.get("retrieval_selected", []) if b["kind"] == "skill"}
        for skill in self.selected_skills:
            if skill.name in injected:
                self.trajectory["used_skill_versions"][skill.name] = skill.version
                if skill.name not in self.trajectory["used_skills"]:
                    self.trajectory["used_skills"].append(skill.name)
                self.skills.mark_usage(skill.name, skill.version, self.trajectory["id"], "injected")

    def _before_tool(self, call):
        self.trajectory["tools"].append({"call": asdict(call), "result": None})

    def _after_tool(self, call, result):
        self.context.state.tool(call, result)
        self.trajectory["tools"][-1]["result"] = asdict(result)
        self.trajectory["messages"].append(asdict(result))
        if len(result.content) > 2400:
            directory = self.config.data_dir / "observations"
            directory.mkdir(exist_ok=True)
            name = hashlib.sha256((self.trajectory["id"] + call.id).encode()).hexdigest()[:24] + ".txt"
            path = directory / name
            path.write_text(result.content, encoding="utf-8")
            try:
                reference = path.relative_to(self.config.cwd).as_posix()
            except ValueError:
                reference = str(path)
            self.context.state.artifacts[call.id] = reference
            self.trajectory["tools"][-1]["artifact"] = reference

    async def run(self, prompt, *, trial_skill=None, learn=None):
        if self.running:
            raise RuntimeError("CodingAgent is already running")
        if not prompt.strip():
            raise ValueError("Prompt cannot be empty")
        self._running = True
        status = "error"
        self.trajectory = dict(id=uuid.uuid4().hex, prompt=prompt, scope=self.scope,
                               started_at=time.time(), status="running", tools=[],
                               messages=[{"role": "user", "content": prompt}], used_skills=[],
                               used_skill_versions={}, context_calls=[],
                               learn=(trial_skill is None) if learn is None else bool(learn),
                               environment={"platform": sys.platform, "shell": "cmd.exe" if os.name == "nt" else "/bin/sh"})
        try:
            if self.trajectory["learn"]:
                self.evolution.consume_feedback(self.scope, prompt, self.trajectory["id"])
            else:
                self.evolution.last_decisions = []
            self.memory_hits = retrieve(self.memory, prompt, self.scope, cwd=self.config.cwd)
            self.selected_skills = self.skills.retrieve(prompt, scope=self.scope, environment=self.trajectory["environment"])
            if trial_skill:
                skill = self.skills.get(trial_skill)
                if not skill or skill.status not in {"candidate", "active", "mature"}:
                    raise ValueError("Trial skill must be a candidate/active/mature skill")
                self.selected_skills = [skill, *[s for s in self.selected_skills if s.name != skill.name]][:3]
            self.trajectory["retrieved_memories"] = [{"id": h["memory"]["id"], "version": h["memory"]["version"]}
                                                       for h in self.memory_hits]
            self.trajectory["retrieved_skills"] = [{"name": s.name, "version": s.version} for s in self.selected_skills]
            blocks = [{"kind": "memory", "id": str(h["memory"]["id"]), "text": format_memories([h]),
                       "score": h["selection_score"]} for h in self.memory_hits]
            for skill in self.selected_skills:
                self.skills.mark_usage(skill.name, skill.version, self.trajectory["id"], "retrieved")
                blocks.append({"kind": "skill", "id": skill.name, "text": format_skills([skill]),
                               "score": 1 + skill.confidence, "required": skill.name == trial_skill})
            self.context.set_sources(SYSTEM_PROMPT + f"\nProject directory: {self.scope}", blocks)
            self.context.state.user(prompt)
            async for event in self.agent.run(prompt):
                if event.type == "run_end":
                    status = event.data["status"]
                else:
                    yield event
                if event.type in {"model_start", "tool_end"}:
                    yield AgentEvent("research_state", self.snapshot())
        finally:
            self.trajectory.update(status=status, finished_at=time.time())
            for step in self.trajectory["tools"]:
                if step["result"] is None:
                    step["result"] = {"is_error": True, "content": "Execution interrupted"}
            try:
                self._save_experience()
            finally:
                self._running = False
        yield AgentEvent("research_state", self.snapshot())
        yield AgentEvent("run_end", {"status": status, "trajectory_id": self.trajectory["id"]})

    def _save_experience(self):
        try:
            if self.trajectory["learn"]:
                self._update_research()
        finally:
            # Preserve the execution evidence even when a research policy fails.
            self.trajectory["context_audit"] = self.context.snapshot()
            self.trajectory["skill_evolution"] = self.evolution.snapshot()
            path = self.config.data_dir / "trajectories.jsonl"
            with path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(self.trajectory, ensure_ascii=False) + "\n")

    def _update_research(self):
        tools = self.trajectory["tools"]
        if tools:
            failures = [s for s in tools if s["result"]["is_error"]]
            changes = [f"{s['call']['name']}: {s['call']['arguments'].get('file_path', '')}"
                       for s in tools if s["call"]["name"] in {"Write", "Edit"} and not s["result"]["is_error"]]
            tests = [s["result"]["content"][:600] for s in tools if s["call"]["name"] == "Bash"
                     and re.search(r"pytest|\btest\b|unittest|tsc|typecheck", str(s["call"]["arguments"].get("command", "")))]
            summary = (f"Task: {self.trajectory['prompt'][:800]}\nStatus: {self.trajectory['status']}\n"
                       f"Changes: {changes}\nTests: {tests}\n"
                       f"Failures: {[s['result']['content'][:400] for s in failures]}")
            self.memory.add(summary, scope=self.scope, source=self.trajectory["id"],
                            confidence=0.6, success=bool(tests) and not failures and self.trajectory["status"] == "completed",
                            metadata={"outcome": self.trajectory["status"], "changes": changes,
                                      "test_observations": tests, "tool_count": len(tools),
                                      "file_fingerprints": fingerprint_files(self.config.cwd,
                                          [s["call"]["arguments"].get("file_path") for s in tools
                                           if s["call"]["name"] in {"Write", "Edit"} and not s["result"]["is_error"]
                                           and s["call"]["arguments"].get("file_path")])})
            for step in tools:
                command = str(step["call"]["arguments"].get("command", ""))
                output = step["result"]["content"]
                if (self.trajectory["status"] == "completed" and step["call"]["name"] == "Bash"
                        and not step["result"]["is_error"] and re.search(r"pytest|\btest\b|unittest|tsc|typecheck", command)
                        and not re.search(r"\bFAILED\b|\bERROR\b|[1-9]\d* failed", output)):
                    self.memory.observe_fact("test-command:" + hashlib.sha256(command.encode()).hexdigest()[:12],
                        f"Observed successful project check command: {command}", scope=self.scope,
                        source=self.trajectory["id"], metadata={"call_id": step["call"].get("id"), "output": output[:400]})
        self.evolution.observe(self.trajectory)
        self.skills.prune()

    def validate_skill(self, name, trajectory_id, useful, saved_calls=0):
        path = self.config.data_dir / "trajectories.jsonl"
        if path.exists():
            with path.open(encoding="utf-8") as file:
                for line in file:
                    trajectory = json.loads(line)
                    if trajectory["id"] == trajectory_id:
                        if name not in trajectory["used_skills"]:
                            raise ValueError("Skill was not used in this trajectory; run a trial first")
                        return self.evolution.validate(name, trajectory, useful=useful, saved_calls=saved_calls)
        raise ValueError("Unknown trajectory")

    def cancel(self):
        self.agent.cancel()

    def snapshot(self):
        return {"model": self.config.model, "base_url": self.config.base_url, "cwd": self.scope,
                "running": self.running, "context": self.context.snapshot(),
                "memory": {"counts": self.memory.counts(), "retrieved": self.memory_hits, **self.memory.stats()},
                "skills": {"selected": list(self.trajectory["used_skills"]) if self.trajectory else [],
                           "retrieval": self.skills.last_retrieval, "evolution": self.evolution.snapshot(),
                           "items": [{**asdict(s), "utility": s.utility, "confidence_lower": s.confidence_lower}
                                     for s in self.skills.all()]},
                "trajectory_id": self.trajectory["id"] if self.trajectory else None}

    def close(self):
        if self.running:
            raise RuntimeError("Cancel and await the active run before closing")
        self.memory.close()
        self.skills.close()
