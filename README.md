# FoxCode Research

FoxCode is a lightweight research-oriented coding agent that combines a minimal tool-using harness with task-aware context compression, project memory and self-evolving skills.

从 [agent_loop.py](packages/fox_agent_core/src/agent_loop.py) 开始阅读主循环。

```text
React / CLI → HTTP + SSE / Python API → CodingAgent
                                      ├── ContextManager
                                      ├── Project Memory
                                      ├── Skills + SkillEvolution
                                      └── Agent → OpenAI adapter → compatible endpoint
                                             └── Read / Write / Edit / Glob / Bash
```

## 运行

Python 3.12+、uv；前端使用 Node.js 22.12+ 和 npm。在仓库根目录安装 Python 依赖：

```bash
uv sync
```

启动工作台（同一个命令会启动 Python 服务和前端）：

```bash
cd desktop
npm install
npm run dev
```

打开终端输出的 `Local` 地址（默认 `http://127.0.0.1:5273`；端口被占用时自动尝试 5274 等后续端口），在右上角「配置模型」或左下角「运行配置」填写模型 ID、API 地址、项目目录和 API Key。
OpenAI、DeepSeek、Qwen、GLM、vLLM 等使用同一个 Chat Completions adapter。
Key 留在服务端内存，接口不回传；留空使用现有或环境密钥。

`npm run dev:web` 只启动前端，适用于已运行服务的情况。也可以单独启动服务并通过环境变量配置：

```bash
export FOX_MODEL=your-model-id
export FOX_BASE_URL=https://your-endpoint/v1
export FOX_API_KEY=your-key
uv run python -m fox_serve --cwd /path/to/project
```
PowerShell 环境变量写法为 `$env:FOX_MODEL="your-model-id"`，其余同理。

也支持 `.env`：将仓库根目录的 [.env.example](.env.example) 复制为 `.env`，填写模型、API 地址和 Key，无需手动设置环境变量。CLI 和服务会先从项目目录（`--cwd` 或前端选定目录）向父目录查找最近的 `.env`；找不到时再从启动目录向上查找，只读取找到的第一个文件。优先级为：显式参数 > 已有环境变量 > `.env` > 默认值。`.env` 已被 Git 忽略；修改后重启服务生效。

界面预览：

![FoxCode Research 工作台](docs/images/workspace.png)

静态页面：先在 `desktop` 执行 `npm run build`，再打开 `http://127.0.0.1:8877`。
可选 Electron 窗口：服务运行后，在 `desktop` 执行 `npm start`。

CLI：

```bash
uv run fox --cwd /path/to/project --model your-model-id "Fix the failing parser test"
uv run fox --json "Inspect the test command"
```

## 三个研究模块

- **Context**：分层信息预算、API usage 校准、迟滞压缩；按完整工具协议组选择原文、压缩观测或淘汰。TaskState 跟踪文件修订与失败/重试证据，用户原文受保护，长观测可通过存档引用重新读取。
- **Memory**：项目事实与具体执行经验。SQLite/FTS5 支持证据去重、事实版本与冲突替代、TTL 和文件指纹；检索采用 BM25、多信号排序及 MMR 风格多样性选择。自动事实先累积不同来源证据，历史事实仍需核验。
- **Skill**：带前置条件、步骤、验证和反例的可复用策略。参考 BearCode 的下一轮反馈窗口、Extractor/Maintainer 与来源审计；新修订作为 Candidate，原有稳定版本继续服务。显式试用和外部反馈绑定实际注入版本，支持归档和回滚。

Memory/Skill 先检索 top-k，再由 Context 预算决定实际注入，Candidate 不自动注入。JSONL trajectory 记录原始观测、版本与研究决策，可用于后续 SWE-bench/RL 实验；当前没有实现 RL 训练或模型 internalization，也没有运行效果评估。

各模块的算法、源码阅读路线、案例、面试追问与后续实验设计见 [三模块学习路线](docs/learning/README.md)、[Context](docs/learning/CONTEXT.md)、[Memory](docs/learning/MEMORY.md)、[Skill Evolution](docs/learning/SKILL_EVOLUTION.md)。

数据在 `<project>/.foxcode/research/`：`memory.sqlite`、`skills.sqlite`、`trajectories.jsonl`、`observations/`。本轮研究字段升级保留已有数据库和轨迹。
「新任务」清空 Context/Working Memory，保留长期数据。旧会话、Markdown Memory、旧 Skill 没有兼容包装或自动迁移，原目录数据保留。切模型会重新组装 CodingAgent 并清空当前 Context。

Read/Write/Edit/Glob/Bash 直接在所选目录运行，没有隔离环境。POSIX shell 使用 `/bin/sh`，Windows 使用 `cmd.exe`；需要 PowerShell 时由命令显式调用。

## 验证与文档

```bash
uv run python -m pytest tests -q
cd desktop
npm test
npm run build
```

完整删除清单、合并映射、Before/After/Why、目录树与实测规模见 [重构报告](docs/REFACTOR_REPORT.md)。研究设计及实验边界见 [架构说明](docs/ARCHITECTURE.md)。
