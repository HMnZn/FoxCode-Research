# fox_coding_agent

详细学习指南：[配置、组装、Hook、轨迹与学习生命周期](../../docs/learning/CODING_AGENT.md) · [全栈学习索引](../../docs/learning/README.md)

![研究策略组装](../../docs/learning/assets/coding-agent.svg)

`CodingAgent` 组合极简 `Agent` 与三个研究策略：

- `ContextManager`：分层预算、usage 校准、任务状态、完整工具组的渐进压缩与存档引用。
- `MemoryStore`：证据去重、项目事实版本、有效期、文件新鲜度、多阶段可解释检索。
- `SkillEvolution` / `SkillStore`：经验候选、下一轮纠正、维护决策、独立修订、稳定版本和外部反馈。

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

`Config.from_env()` 支持项目/启动目录向上查找 `.env`。可传 `stream_fn` 模拟模型。使用 `run(prompt, trial_skill=name)` 显式试用最新 Candidate，再通过 `validate_skill(name, trajectory_id, useful=True)` 接收外部反馈。验证按轨迹实际注入版本进行，修改指令不复用旧版反馈，也不覆盖仍在服务的已验证版本。

显式 trial 默认 `learn=False`，不把验证轨迹沉淀到 Memory/Skill；普通任务默认学习。可显式设置 `learn`，轨迹和注入统计始终保留。

[学习路线](../../docs/learning/README.md) · [Context](../../docs/learning/CONTEXT.md) · [Memory](../../docs/learning/MEMORY.md) · [Skill Evolution](../../docs/learning/SKILL_EVOLUTION.md)

机制验证：`uv run python -m pytest tests/test_research.py tests/test_research_policies.py -q`。
