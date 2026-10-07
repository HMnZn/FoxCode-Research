# fox_coding_agent

`CodingAgent` 组合 `Agent`、`ContextManager`、`MemoryStore`、`SkillStore`、`SkillEvolution`。`Config` 是唯一配置对象。任务开始检索，before_model 压缩，模型/工具 callback 更新 TaskState 与 trajectory，结束时保存经验和候选 Skill。

Working Memory 在 TaskState 中；Episodic/Semantic 进入项目 SQLite。提取只产生 Candidate，独立试用及明确 usefulness 证据才升级。

```python
from fox_coding_agent.src import CodingAgent, Config

async def example():
    coding = CodingAgent(Config.from_env(cwd="."))
    try:
        async for event in coding.run("Fix the failing test"):
            print(event.type, event.data)
    finally:
        coding.close()
```

可传入 `stream_fn` 模拟模型，`run(prompt, trial_skill=name)` 试用 Candidate，再调用 `validate_skill(name, trajectory_id, useful=True)`。来源轨迹不能验证自身，相同证据 ID 只计一次，改变指令会重置验证证据并升级版本。

设计见 [架构说明](../../docs/ARCHITECTURE.md)。
验证：仓库根目录 `uv run python -m pytest tests/test_research.py -q`。
