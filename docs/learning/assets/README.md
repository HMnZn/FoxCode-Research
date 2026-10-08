# 学习文档配图

这些 SVG 是根据当前仓库源码绘制的教学示意图。图中文字与卡片编号可直接编辑，无需图像生成服务；编号通常从上排左向右，再从下排右向左阅读。

| 图片 | 对应文档 | 核对入口 |
| --- | --- | --- |
| [architecture.svg](architecture.svg) | 学习总览 | 三个包、fox_serve、desktop 的入口 |
| [model-adapter.svg](model-adapter.svg) | fox_ai | openai_provider.stream / convert_context |
| [agent-loop.svg](agent-loop.svg) | Agent Core | Agent.run / agent_loop / Hooks |
| [coding-agent.svg](coding-agent.svg) | CodingAgent | run / 四个 Hook / _save_experience |
| [context-budget.svg](context-budget.svg) | Context | ContextManager.prepare / compress |
| [memory-retrieval.svg](memory-retrieval.svg) | Memory | observe_fact / retrieve |
| [skill-versions.svg](skill-versions.svg) | Skill | propose / serving / validate / record |
| [serve-transport.svg](serve-transport.svg) | Serve | create_app.run / produce / events |
| [desktop-state.svg](desktop-state.svg) | Desktop | send / consumeEvents / receive |

总览展示模块关系，其余图展示主要流程；分支与异常请结合正文中的 Mermaid 和源码。Context 阈值、Memory 候选上限和 Skill 门槛是当前实现参数，不是实验收益。

Desktop 另引用 [workspace.png](../../images/workspace.png)、[configuration.png](../../images/configuration.png)、[mobile.png](../../images/mobile.png)，三张都是仓库已有的界面预览。
