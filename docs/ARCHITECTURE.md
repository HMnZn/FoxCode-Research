# Architecture and research boundaries

FoxCode 保持三层依赖：`fox_ai` → 模型协议，`fox_agent_core` → 工具循环和 Hook，`fox_coding_agent` → 项目编排与研究策略。完整学习材料从 [三模块学习路线](learning/README.md) 开始。

## Task-State-Aware Context

ContextManager 在 `before_model` 分配 system/schema、保护的用户原文、工作状态、Memory/Skill 检索块和消息历史。预算预留生成空间；UTF-8 估算使用实际 API input usage 校准。90% 触发、75% 目标的迟滞减少反复压缩。

压缩单位是完整 assistant/tool-result 协议组。先保护真实用户消息和最新执行组，再根据任务关联、文件依赖、未解决失败、重复性和单位 token 效用选择旧组。长工具结果先做 head/diagnostic/tail 抽取，预算允许时恢复原文，无法保留的组才淘汰。

TaskState 保存文件读取修订、失败/重试和检查证据。长观测保存在 observations 文件中，原始 trajectory 也保留完整工具返回结果；压缩片段带来源引用。调用参数和用户原文不截断，保护信息超出硬预算时明确报错。

这不是 provider 精确 tokenizer，也不是通用因果图或自动补读系统。细节与追问见 [Context 学习文档](learning/CONTEXT.md)。

## Evidence-Aware Project Memory

Working Memory 位于 TaskState。Episodic 保存具体执行经历；Semantic 保存明确事实或受到工具观测支持的窄范围项目知识。

SQLite/FTS5 之外增加 evidence、内容去重、同 scope/key 的事实修订、TTL、文件指纹和手动失效。自动检查命令事实先 provisional，两个不同来源轨迹支持后 active；不会从模型“已完成”的文本直接推断任务正确。

检索流程为项目/global 和有效性过滤 → BM25 候选 → coverage/recency/confidence/scope/staleness 排序 → MMR 风格多样性选择 → Context 的 token 预算。返回评分拆解和 stale 文件路径，历史事实仍需要模型使用 Read/Glob/Bash 验证。

没有 embedding 搜索、自然语言矛盾检测或保证记忆为真的验证器。细节见 [Memory 学习文档](learning/MEMORY.md)。

## Versioned Experience-Driven Skill Evolution

参考本机 BearCode 的 pending feedback window、Extractor/Maintainer、add/merge/discard、provenance/history/usage 思路；FoxCode 使用轻量规则和 SQLite 实现，没有复制在线效果评测系统。

```text
失败/恢复、重复失败、用户纠正
  -> 有来源的 experience hypothesis
  -> 结构化 Candidate（前置条件/步骤/验证/反例）
  -> 相同 family/scope/environment 的维护决策
  -> 候选修订与稳定 serving version 分开
  -> 显式试用 + 外部版本级反馈
  -> Active / Mature / Reject / Prune / Rollback
```

`skills` 保存最新修订，`skill_versions` 保留各版内容，`skill_champions` 指向稳定版本，`skill_events` 保存更新来源。新候选不覆盖旧稳定版本，改变策略内容需要新版本并重置反馈证据。

普通检索只服务适用的 Active/Mature 版本，按元信息加权 BM25 风格评分和证据下界排序；每个 family 最多一个，默认 top-3。显式 trial 使用最新未归档修订。

每条轨迹分别记录 retrieved 和实际 injected 的版本。`used_skills` 的准确含义是“注入过”，不是“证明模型采用”。反馈只能更新实际注入版本；提取来源不能自证；同一轨迹不能重复计数。旧轨迹缺少版本信息时，发生修订后拒绝模糊反馈。

反馈均由外部实验或人工提供。Beta mean、Wilson 下界、utility 和门槛是可解释策略统计；champion 名称表示稳定服务指针，不表示已完成反事实性能比较。细节及 BearCode 对照见 [Skill 学习文档](learning/SKILL_EVOLUTION.md)。

## 执行、观测和数据

```text
项目/.foxcode/research/
├── memory.sqlite       # 事实/经验、FTS、支持证据
├── skills.sqlite       # 修订、稳定版本、来源事件、usage、待反馈窗口
├── trajectories.jsonl  # 原始消息/工具结果、实际注入版本、context 调用审计
└── observations/       # 较长工具观测的可读取存档
```

原始轨迹不会因 Context 淘汰消息而丢失。每次任务的 `context_calls` 记录注入选择，`context_audit` 记录最终状态、最后压缩决策和近期预算历史，`skill_evolution` 记录本轮候选维护结果。

已有 research 数据采用增加字段/版本表的升级方式，不删除用户数据。工具直接在所选项目运行；外部实验环境负责隔离和任务判分。

HTTP/SSE 仍是单 Agent、单任务 busy guard、asyncio cancellation。新增知识失效、Skill 历史与回滚接口；没有队列调度器、插件框架、session branching 或 sandbox 系统。

本轮实现并验证机制，不运行收益评测。各学习文档列出外部可做的 baseline/ablation 和指标，尚无任务成功率提升、token 降幅或技能泛化效果的结论。

`learn=False` 关闭当前执行的 Memory/Skill 沉淀和待反馈窗口更新，保留 Context、轨迹与注入统计；显式 Skill trial 默认关闭学习，普通任务默认开启。这个开关供独立验证使用，不代替实验侧的数据切分与版本冻结。
