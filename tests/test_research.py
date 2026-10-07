import json
import time
import pytest
from fox_ai.src import (AssistantMessage, Context, Done, Model, TextDelta,
                        ToolCall, ToolResultMessage, UserMessage)
from fox_coding_agent.src import CodingAgent, Config, ContextManager
from fox_coding_agent.src.context.scorer import score
from fox_coding_agent.src.memory import MemoryStore
from fox_coding_agent.src.memory.retrieval import retrieve, format_memories
from fox_coding_agent.src.skills import Skill, SkillStore, SkillEvolution, extract_experience


def test_task_aware_compression_protects_constraints_and_pairs():
    manager = ContextManager(budget=2600)
    user = UserMessage("Fix parser. 必须保留公开 API，不要增加依赖。")
    manager.state.user(user.content)
    context = Context([user])
    for i in range(8):
        call = ToolCall(str(i), "Read", {"file_path": "parser.py"})
        context.messages.extend([AssistantMessage(tool_calls=[call]),
                                 ToolResultMessage(str(i), "Read", "old source\n" * 1500)])
    failure = ToolResultMessage("test", "Bash", "FAILED parser test: unexpected EOF", True)
    call = ToolCall("test", "Bash", {"command": "pytest parser"})
    manager.state.tool(call, failure)
    context.messages.extend([AssistantMessage(tool_calls=[call]), failure,
                             AssistantMessage("Next: fix parser edge case")])
    manager.prepare(context)
    assert manager.compressions == 1
    assert user in context.messages and user.content.endswith("不要增加依赖。")
    assert "Known Failures" in context.messages[0].content
    assert failure in context.messages
    assert manager.last["tokens"] <= manager.budget
    ids = {c.id for m in context.messages if isinstance(m, AssistantMessage) for c in m.tool_calls}
    results = {m.tool_call_id for m in context.messages if isinstance(m, ToolResultMessage)}
    assert ids == results
    assert score(user, 0, 10, manager.state).total > score(ToolResultMessage("r", "Read", "old"), 0, 10, manager.state).total
    # Compressing again must not turn the old summary into protected user input.
    context.messages.extend([AssistantMessage(tool_calls=[ToolCall("new", "Read", {})]),
                             ToolResultMessage("new", "Read", "large" * 10000)])
    manager.prepare(context)
    assert sum(m.content.startswith("Working Context") for m in context.messages) == 1


def test_oversized_protected_input_reports_budget():
    manager = ContextManager(512)
    user = UserMessage("必须保留" * 3000)
    manager.state.user(user.content)
    context = Context([user])
    with pytest.raises(ValueError, match="Protected"):
        manager.prepare(context)
    assert user in context.messages and manager.last["over_budget"]


def test_project_memory_persistence_ranking_and_verification(tmp_path):
    path = tmp_path / "memory.sqlite"
    store = MemoryStore(path)
    id = store.add("Run pytest for parser tests", memory_type="semantic", scope="project-a", confidence=0.9)
    store.add("Run pytest for parser tests", scope="project-b")
    store.add("用户偏好：不要增加依赖", scope="project-a", verify=False)
    store.close()
    store = MemoryStore(path)
    hits = retrieve(store, "parser tests", "project-a")
    assert [h["memory"]["id"] for h in hits] == [id]
    assert set(hits[0]["breakdown"]) == {"bm25", "recency", "scope", "confidence", "success", "coverage", "verified", "stale"}
    assert "verification required" in format_memories(hits)
    assert "Read/Glob/Bash" in format_memories(hits)
    assert retrieve(store, "增加依赖", "project-a")
    assert store.get(id).source == "user"
    with pytest.raises(ValueError):
        store.add("working", memory_type="working")
    store.close()


def test_skill_lifecycle_heldout_validation_update_prune(tmp_path):
    store = SkillStore(tmp_path / "skills.sqlite")
    evolution = SkillEvolution(store)
    skill = Skill("windows-env", "Windows shell environment", "Windows export fails",
                  "Use PowerShell $env:NAME after verifying the shell", ["windows", "environment"],
                  source_trajectory=["source"])
    store.propose(skill)
    assert store.retrieve("windows environment") == []
    with pytest.raises(ValueError, match="held-out"):
        evolution.validate(skill.name, {"id": "source", "status": "completed"}, useful=True)
    for i in range(2):
        evolution.validate(skill.name, {"id": str(i), "status": "completed"}, useful=True)
    active = store.get(skill.name)
    assert active.status == "active" and len(store.retrieve("windows environment")) == 1
    evolution.validate(skill.name, {"id": "1", "status": "completed"}, useful=True)
    assert store.get(skill.name).success_count == 2
    for i in range(2, 5):
        evolution.validate(skill.name, {"id": str(i), "status": "completed"}, useful=True)
    assert store.get(skill.name).status == "mature"
    # Changing the strategy must not reuse the old validation evidence.
    skill.instructions = "Verify PowerShell then use Set-Item Env:NAME"
    skill.source_trajectory = ["new-source"]
    updated = store.propose(skill)
    assert updated.version == 2 and updated.status == "candidate" and updated.success_count == 0
    for id in ["bad1", "bad2"]:
        store.record(skill.name, success=False, evidence_id=id)
    assert store.get(skill.name).status == "rejected"
    store.close()


async def test_complete_coding_task_records_experience(tmp_path):
    count = 0
    async def model(model, context, options):
        nonlocal count
        count += 1
        if count == 1:
            assert "historical" in context.system_prompt.lower()
            calls = [ToolCall("a", "Write", {"file_path": "src/main.py", "content": "print('bad')"})]
        elif count == 2:
            calls = [ToolCall("b", "Edit", {"file_path": "src/main.py", "old_text": "missing", "new_text": "good"})]
        elif count == 3:
            assert context.messages[-1].is_error
            calls = [ToolCall("c", "Edit", {"file_path": "src/main.py", "old_text": "bad", "new_text": "good"})]
        elif count == 4:
            calls = [ToolCall("d", "Read", {"file_path": "src/main.py"})]
        elif count == 6:
            calls = [ToolCall("e", "Read", {"file_path": "src/main.py"})]
        else:
            if count in {5, 7}:
                assert "good" in context.messages[-1].content
            yield TextDelta("Fixed")
            yield Done(AssistantMessage("Fixed"))
            return
        yield Done(AssistantMessage(tool_calls=calls))
    coding = CodingAgent(Config(cwd=tmp_path, model="fake"), stream_fn=model)
    events = [e async for e in coding.run("Fix main.py without dependencies")]
    assert events[-1].data["status"] == "completed"
    assert (tmp_path / "src/main.py").read_text() == "print('good')"
    assert coding.memory.counts() == {"episodic": 1}
    assert len(coding.skills.all()) == 1 and coding.skills.all()[0].status == "candidate"
    name = coding.skills.all()[0].name
    trajectory = json.loads((coding.config.data_dir / "trajectories.jsonl").read_text())
    assert len(trajectory["tools"]) == 4 and trajectory["status"] == "completed"
    # Explicit trial allows held-out candidate validation without auto-injection.
    await collect(coding.run("Verify main.py", trial_skill=name, learn=True))
    id = coding.trajectory["id"]
    assert name in coding.trajectory["used_skills"]
    episode = coding.memory.db.execute("SELECT content FROM memories ORDER BY id DESC LIMIT 1").fetchone()
    # A later verification task must not claim the previous task's writes.
    assert "Verify main.py" in episode[0] and "Changes: []" in episode[0]
    coding.validate_skill(name, id, useful=True)
    assert coding.skills.get(name).success_count == 1
    coding.close()


async def collect(events):
    return [event async for event in events]


def test_repeated_failure_correction_and_skill_pruning(tmp_path):
    step = {"call": {"name": "Bash", "arguments": {"command": "export X=1"}},
            "result": {"is_error": True, "content": "export is not recognized"}}
    trajectory = {"id": "source", "prompt": "纠正：在 PowerShell 使用 $env:X=1", "status": "completed",
                  "tools": [step, step]}
    candidates = extract_experience(trajectory)
    assert len(candidates) == 2
    assert any(s.name.startswith("correction-") for s in candidates)
    store = SkillStore(tmp_path / "skills.sqlite")
    store.propose(candidates[0])
    for id in ["trial1", "trial2"]:
        store.record(candidates[0].name, success=True, evidence_id=id)
    skill = store.get(candidates[0].name)
    assert skill.status == "active"
    store.prune(now=skill.last_used + 91 * 86400)
    assert store.get(skill.name).status == "pruned" and not store.retrieve("Bash")
    store.close()
