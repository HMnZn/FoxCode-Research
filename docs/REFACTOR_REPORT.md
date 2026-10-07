# FoxCode 精简重构报告

2026-10-07，按照根目录 `重构.md` 实施；允许 breaking changes。修改前工作区存在大量用户未提交修改，没有使用 git reset。源码快照：`/tmp/foxcode-before-refactor-1791367189/source.tar.gz`；规模基线来自同目录 `manifest.json`，不是 Git HEAD。`.env`、`.venv`、本地 `.foxcode` 和 FrogNano 参考目录没有改动。

## Before / After / Why

| 层 | Before | After | Why |
| --- | --- | --- | --- |
| fox_ai | 多协议 provider、registry、credentials、retry、capability、sampling | 一个薄 OpenAI-compatible adapter，五文件，五事件 | 学习模型边界，所有厂商通过 base_url/api_key/model 接入 |
| fox_agent_core | loop + harness + session + compaction + scheduler | Agent、可读 loop、五 callback、取消、五工具 | 让模型→工具→observation 主流程直接可见 |
| fox_coding_agent | Runtime/Session/Registry/Extension/Trust/Permission/Sandbox 多层包装 | CodingAgent + Config + Context/Memory/Skills | 把研究策略放在项目层，允许独立实验 |
| fox_serve | NDJSON、审批、会话分支、恢复、配置服务、扩展目录 | 单 Agent HTTP/SSE，7 个 API 路由 | 直接将 UI 操作映射到 CodingAgent |
| desktop | 多页面/store/IPC/mock/terminal/权限 UI | React 单页 + 原生 fetch SSE + 薄 Electron 窗口 | 展示任务与研究状态，减少产品复杂度 |

Core 的五个工具来自原 Coding tools 的必需能力，下沉到 core；Compaction 上移到 Coding context。
没有旧/新双实现或 deprecated wrapper。旧会话/Markdown Memory/Skill 不迁移，新实验存储使用项目 `.foxcode/research/`；已有本地数据保留。

## Merged

```text
fox_ai/models + credentials + provider factories → Coding Config + Model/StreamOptions
fox_ai/event_stream + providers/openai_provider → fox_ai/openai_provider + async generator
fox_agent_core/harness/hooks + coding/extensions callbacks → fox_agent_core/hooks.py
coding/core/tools → fox_agent_core/tools/{read,write,edit,glob,bash}.py
coding/core/runtime + agent_session + model_runtime → coding_agent.py
coding/core/settings + model_config + credentials → config.py
core/harness/compaction → coding/context/{manager,scorer,compressor,state}.py
coding/extensions/memory/* → coding/memory/{store,retrieval}.py
coding/core/skills + extensions/skill_evolution/* → coding/skills/{store,evolution}.py
fox_serve/host + configuration + protocol + server + cli → fox_serve/app.py + __main__.py
desktop/pages + components + stores → desktop/src/App.tsx + styles.css
desktop/bridge + electron/sidecar protocol → desktop/src/api.ts + types.ts
desktop/electron/main + preload + terminal → 薄 electron/main.js
旧 architecture guides + sandbox docs → docs/ARCHITECTURE.md
旧重构记录 → 本报告；三个 Notebook 改写为可执行新 API 示例
```

这里的合并表示职责收敛后的重写，生产功能按要求删除，并非保留旧文件全部行为。

## 新目录

```text
packages/
├── fox_ai/
│   ├── pyproject.toml / README.md / DEEPSEEK_MODEL_LAB.ipynb
│   └── src/
│       ├── __init__.py
│       ├── types.py
│       ├── events.py
│       ├── stream.py
│       └── openai_provider.py
├── fox_agent_core/
│   ├── pyproject.toml / README.md / AGENT_CORE_LAB.ipynb
│   └── src/
│       ├── __init__.py
│       ├── agent.py
│       ├── agent_loop.py
│       ├── types.py
│       ├── events.py
│       ├── hooks.py
│       └── tools/
│           ├── __init__.py
│           ├── read.py
│           ├── write.py
│           ├── edit.py
│           ├── glob.py
│           └── bash.py
└── fox_coding_agent/
    ├── pyproject.toml / README.md / CODING_AGENT_LAB.ipynb
    └── src/
        ├── __init__.py
        ├── __main__.py
        ├── cli.py
        ├── config.py
        ├── coding_agent.py
        ├── context/
        │   ├── __init__.py
        │   ├── manager.py
        │   ├── scorer.py
        │   ├── compressor.py
        │   └── state.py
        ├── memory/
        │   ├── __init__.py
        │   ├── store.py
        │   └── retrieval.py
        └── skills/
            ├── __init__.py
            ├── store.py
            └── evolution.py

fox_serve/
├── __init__.py
├── __main__.py
├── app.py
└── README.md

desktop/
├── src/
│   ├── App.tsx
│   ├── api.ts
│   ├── types.ts
│   ├── main.tsx
│   ├── styles.css
│   ├── App.test.tsx
│   └── api.test.ts
├── electron/main.js
├── package.json / package-lock.json
├── vite.config.mts / vitest.config.mts / vitest.setup.ts
├── tsconfig.json / index.html
└── README.md

tests/
├── test_ai.py
├── test_agent.py
├── test_research.py
├── test_server.py
└── test_architecture.py

docs/
├── ARCHITECTURE.md
├── REFACTOR_REPORT.md
└── refactor_metrics.json
```

## 三个核心创新

**Task-State-Aware Context Compression**：TaskState 保存目标/约束/计划/文件/修改/观察/失败/测试/当前状态；utility 由 recency、task relevance、dependency importance、failure importance、explicit constraint 组成。用户原文保护，近期与高 utility 消息组优先保留；旧 Read/重复输出降权。工具调用与结果不拆开。超出预算且 protected 信息无法容纳时明确报错。

**Project-Centric Memory**：Working 状态在 TaskState；Episodic/Semantic 使用 SQLite/FTS5/BM25，加小的 recency/scope/confidence/success 奖励。只召回当前项目或 global。历史事实以 historical hint 注入，要求 Read/Glob/Bash verify-before-use。当前这是提示词策略，没有强制验证器。

**Experience-Driven Self-Evolving Skill**：失败→恢复、重复错误、显式纠正提取 Candidate。检索仅 Active/Mature top-k；Candidate 需显式 trial。held-out 轨迹的 usefulness 反馈才会升级，相同证据不可重复计数、来源不能验证自身。两次成功可 Active；五次成功且置信度达到阈值可 Mature；utility 低则 Reject/Prune。改变指令升级版本并重新验证。Utility = successes − failures + saved tool calls。

详细 heuristic、阈值和可做的消融实验见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 数据流

```text
User
 ↓
Context Manager
 ↓
Memory / Skill Retrieval
 ↓
Agent
 ↓
LLM
 ↓
Tool
 ↓
Trajectory
 ├─→ Context Compression
 ├─→ Memory
 └─→ Skill Evolution
```

实际实现先在任务开始检索并组装 prompt，随后每次 before_model 检查输入预算；模型/工具 callbacks 更新 task state，任务结束保存原始 trajectory 与经验。Compression 不等于 Memory。

## 实际验证

Linux Python 环境使用 `/tmp/foxcode-refactor-venv`，没有替换已有 Windows `.venv`。Windows Node v22.23.2 执行现有前端 npm 工具链。

| 实际命令 | 结果 |
| --- | --- |
| `UV_PROJECT_ENVIRONMENT=/tmp/foxcode-refactor-venv uv sync --python 3.14` | 完成 workspace 安装并更新 uv.lock |
| `/tmp/foxcode-refactor-venv/bin/python -m pytest tests/test_ai.py tests/test_agent.py -q` | Phase 1/2 首轮 9 passed |
| `/tmp/foxcode-refactor-venv/bin/python -m pytest tests -q` | 最终 20 passed |
| `cd desktop && npm test` | 2 test files / 4 tests passed |
| `cd desktop && npm run build` | TypeScript + Vite 成功，主 JS gzip 约 72.5 KB |
| `cd desktop && npm update source-map-js --ignore-scripts` | 移除 380 个无用已安装包，更新间接依赖 |
| `cd desktop && npm audit` | 0 vulnerabilities |
| `python -m compileall -q packages fox_serve` | 成功 |
| `uv run --no-sync fox --help` / `uv run --no-sync python -m fox_serve --help` | CLI / Server 入口可用 |
| 三个 Notebook code cells 使用 `ast.PyCF_ALLOW_TOP_LEVEL_AWAIT` 执行 | 3/3 成功，默认不调用真实模型 |
| 现有 Windows Electron 执行 `.build-cache/refactor-demo/preview.cjs` | 界面 E2E 成功：Prompt、真实文件工具、失败→恢复、完成文本、Memory、Candidate Skill |
| `git diff --check -- packages desktop fox_serve docs tests README.md pyproject.toml uv.lock` | 成功 |

HTTP 测试启动真实 uvicorn：确认首个文本 delta 在模型未完成时已到达、运行中重入返回 409、停止返回 cancelled。另一个测试通过真实 OpenAI SDK 连接 mock-compatible HTTP endpoint，完成 Write → result → model → SSE 全链路。Electron 使用确定性假模型与真实工具，不属于真实模型效果测试。

当前宿主环境运行 Electron 时需要清除 `ELECTRON_RUN_AS_NODE`，验证脚本使用独立 profile、软件渲染和测试用 Chromium flags；这些 flags 没有加入产品代码。截图保存在 `.build-cache/refactor-demo/ui.png`。旧真实模型报告已标为历史，不能作为本次重构的验证依据。

完整 `git diff --check` 仍会指出修改前 `.gitignore` 的 CRLF，未改动该用户文件；本轮路径检查通过。

## 代码规模

采用物理行数，包括注释和空行。统计脚本不计 Notebook、文档、CSS、node_modules、生成产物或本地数据；下面按目录比较的 server 行含旧 server tests，packages 行含旧 fixtures。完整计数在 [refactor_metrics.json](refactor_metrics.json)。

| 范围 | 源码文件数 | LOC |
| --- | --- | --- |
| `packages/fox_ai/src` | 17 → 5 | 4,016 → 237 |
| `packages/fox_agent_core/src` | 12 → 12 | 1,985 → 310 |
| `packages/fox_coding_agent/src` | 54 → 16 | 10,758 → 736 |
| `fox_serve` | 25 → 3 | 9,419 → 195 |
| `desktop/src` | 100 → 6 | 25,183 → 428 |
| `desktop/electron` | 4 → 1 | 1,023 → 8 |
| `desktop/scripts` | 7 → 0 | 752 → 0 |
| `tests` | 16 → 5 | 4,000 → 485 |

去除测试/fixtures 后，运行 Python：**92 → 36 文件，22,978 → 1,478 LOC**。
三层 package 实现模块（排除 `__init__`、`__main__`、fixtures）：**69 → 25**。
前端运行 TS/TSX 和 Electron 的统计可从 JSON 去掉 `.test` 文件得到；CSS 单独保留一份小文件。

## 边界与后续实验

- token 估算和 utility 是 heuristic，未承诺精确 tokenizer 上限或最优保留策略。
- Verify-before-use 是明确的模型行为要求，还需通过过期知识任务评测效果。
- Candidate 恢复抽取不保证因果关系；usefulness 由独立实验/用户反馈提供，不自动自证。
- 当前没有 RL 训练、SWE-bench adapter、模型 internalization，也没有自动 LLM 策略归纳。
- 直接工具执行适合本地研究；未来 rollout 的隔离与判分由外部实验环境承担。

## Deleted：完整实际删除文件

共 286 个修改前存在、现在不存在的源文件/资源/文档。只列实际删除，不把重写的同名文件算删除；包含旧 tests 和 fixtures。

```text
Deleted:
desktop/electron/preload.js
desktop/electron/sidecar.js
desktop/electron/terminal.js
desktop/scripts/dev.mjs
desktop/scripts/electron-bin.mjs
desktop/scripts/fox-icon.html
desktop/scripts/icon.mjs
desktop/scripts/make-icon.mjs
desktop/scripts/prepare-node-pty.mjs
desktop/scripts/real-e2e-driver.js
desktop/scripts/shot.mjs
desktop/src/bridge/index.ts
desktop/src/bridge/ipc.test.ts
desktop/src/bridge/ipc.ts
desktop/src/bridge/mock/mockHost.ts
desktop/src/bridge/mock/scenario.ts
desktop/src/bridge/native.ts
desktop/src/bridge/terminal.ts
desktop/src/bridge/types.ts
desktop/src/components/brand/Fox.tsx
desktop/src/components/chat/Composer.test.tsx
desktop/src/components/chat/Composer.tsx
desktop/src/components/chat/MessageList.test.tsx
desktop/src/components/chat/MessageList.tsx
desktop/src/components/chat/PermissionPrompt.tsx
desktop/src/components/chat/QueuedMessages.test.tsx
desktop/src/components/chat/QueuedMessages.tsx
desktop/src/components/chat/SessionStatusBar.test.tsx
desktop/src/components/chat/SessionStatusBar.tsx
desktop/src/components/chat/ToolCallCard.tsx
desktop/src/components/chat/TraceList.tsx
desktop/src/components/content/CodeBlock.tsx
desktop/src/components/content/ContentParts.test.tsx
desktop/src/components/content/ContentParts.tsx
desktop/src/components/content/DiffView.tsx
desktop/src/components/content/JsonViewer.tsx
desktop/src/components/content/Markdown.tsx
desktop/src/components/content/ToolOutput.tsx
desktop/src/components/content/index.ts
desktop/src/components/layout/CommandPalette.tsx
desktop/src/components/layout/Inspector.test.tsx
desktop/src/components/layout/Inspector.tsx
desktop/src/components/layout/Sidebar.test.tsx
desktop/src/components/layout/Sidebar.tsx
desktop/src/components/layout/Splitter.tsx
desktop/src/components/layout/TerminalPanel.test.tsx
desktop/src/components/layout/TerminalPanel.tsx
desktop/src/components/layout/TitleBar.tsx
desktop/src/components/sessions/RenameDialog.tsx
desktop/src/components/sessions/SessionMenu.tsx
desktop/src/components/settings/SettingsControlPlane.test.tsx
desktop/src/components/settings/SettingsControlPlane.tsx
desktop/src/components/ui/Button.tsx
desktop/src/components/ui/Chip.tsx
desktop/src/components/ui/Dialog.tsx
desktop/src/components/ui/EmptyState.tsx
desktop/src/components/ui/Field.tsx
desktop/src/components/ui/IconButton.tsx
desktop/src/components/ui/Kbd.tsx
desktop/src/components/ui/Menu.tsx
desktop/src/components/ui/ProgressBar.tsx
desktop/src/components/ui/SegmentedControl.tsx
desktop/src/components/ui/Select.tsx
desktop/src/components/ui/Spinner.tsx
desktop/src/components/ui/Switch.tsx
desktop/src/components/ui/Tabs.tsx
desktop/src/components/ui/Toaster.tsx
desktop/src/components/ui/Tooltip.tsx
desktop/src/components/ui/index.ts
desktop/src/components/workspace/FilePreview.test.tsx
desktop/src/components/workspace/FilePreview.tsx
desktop/src/components/workspace/FilesTab.tsx
desktop/src/components/workspace/WorkspaceMenu.tsx
desktop/src/components/workspace/WorkspacePicker.tsx
desktop/src/lib/cn.ts
desktop/src/lib/diff.test.ts
desktop/src/lib/diff.ts
desktop/src/lib/format.ts
desktop/src/lib/highlight.ts
desktop/src/lib/preview.test.ts
desktop/src/lib/preview.ts
desktop/src/lib/terminalText.test.ts
desktop/src/lib/terminalText.ts
desktop/src/pages/ChatPage.test.tsx
desktop/src/pages/ChatPage.tsx
desktop/src/pages/ExtensionsPage.test.tsx
desktop/src/pages/ExtensionsPage.tsx
desktop/src/pages/SessionsPage.tsx
desktop/src/pages/SettingsPage.tsx
desktop/src/pages/SkillsPage.tsx
desktop/src/pages/UsagePage.tsx
desktop/src/store/filesStore.ts
desktop/src/store/pinStore.test.ts
desktop/src/store/pinStore.ts
desktop/src/store/railStore.test.ts
desktop/src/store/railStore.ts
desktop/src/store/sessionStore.test.ts
desktop/src/store/sessionStore.ts
desktop/src/store/terminalStore.test.ts
desktop/src/store/terminalStore.ts
desktop/src/store/timeline.test.ts
desktop/src/store/timeline.ts
desktop/src/store/toastStore.ts
desktop/src/store/uiStore.test.ts
desktop/src/store/uiStore.ts
desktop/src/store/workspaceStore.test.ts
desktop/src/store/workspaceStore.ts
desktop/src/styles/globals.css
desktop/src/types/protocol.ts
docs/FILESYSTEM_AND_SANDBOX.md
fox_serve/approvals.py
fox_serve/cli.py
fox_serve/configuration.py
fox_serve/extension_catalog.py
fox_serve/host.py
fox_serve/protocol.py
fox_serve/scripts/ndjson_client.py
fox_serve/scripts/real_e2e_suite.py
fox_serve/server.py
fox_serve/sessions.py
fox_serve/tests/__init__.py
fox_serve/tests/_tmp.py
fox_serve/tests/test_agent_state.py
fox_serve/tests/test_configuration.py
fox_serve/tests/test_cwd.py
fox_serve/tests/test_extensions.py
fox_serve/tests/test_files.py
fox_serve/tests/test_policy.py
fox_serve/tests/test_protocol.py
fox_serve/tests/test_replay.py
fox_serve/tests/test_server.py
fox_serve/tests/test_sessions.py
fox_serve/workspace_files.py
packages/fox_agent_core/ARCHITECTURE_GUIDE.md
packages/fox_agent_core/src/_async.py
packages/fox_agent_core/src/event_stream.py
packages/fox_agent_core/src/harness/__init__.py
packages/fox_agent_core/src/harness/compaction.py
packages/fox_agent_core/src/harness/events.py
packages/fox_agent_core/src/harness/harness.py
packages/fox_agent_core/src/harness/hooks.py
packages/fox_agent_core/src/harness/session.py
packages/fox_ai/ARCHITECTURE_STUDY.md
packages/fox_ai/src/_async.py
packages/fox_ai/src/constrained_sampling.py
packages/fox_ai/src/credentials.py
packages/fox_ai/src/event_stream.py
packages/fox_ai/src/exceptions.py
packages/fox_ai/src/models.py
packages/fox_ai/src/partial_json.py
packages/fox_ai/src/provider_retry.py
packages/fox_ai/src/providers/anthropic_provider.py
packages/fox_ai/src/providers/faux.py
packages/fox_ai/src/providers/openai_provider.py
packages/fox_ai/src/retry.py
packages/fox_ai/src/user_agent.py
packages/fox_coding_agent/ARCHITECTURE_GUIDE.md
packages/fox_coding_agent/src/core/_io.py
packages/fox_coding_agent/src/core/agent_session.py
packages/fox_coding_agent/src/core/credentials.py
packages/fox_coding_agent/src/core/extensions.py
packages/fox_coding_agent/src/core/interaction.py
packages/fox_coding_agent/src/core/model_config.py
packages/fox_coding_agent/src/core/model_registry.py
packages/fox_coding_agent/src/core/model_runtime.py
packages/fox_coding_agent/src/core/paths.py
packages/fox_coding_agent/src/core/permissions.py
packages/fox_coding_agent/src/core/plan_tool.py
packages/fox_coding_agent/src/core/resources.py
packages/fox_coding_agent/src/core/runtime.py
packages/fox_coding_agent/src/core/sandbox.py
packages/fox_coding_agent/src/core/session_layout.py
packages/fox_coding_agent/src/core/session_manager.py
packages/fox_coding_agent/src/core/settings.py
packages/fox_coding_agent/src/core/skills.py
packages/fox_coding_agent/src/core/system_prompt.py
packages/fox_coding_agent/src/core/tool_registry.py
packages/fox_coding_agent/src/core/tools.py
packages/fox_coding_agent/src/core/trust.py
packages/fox_coding_agent/src/extensions/__init__.py
packages/fox_coding_agent/src/extensions/mcp/MCP_DESIGN.md
packages/fox_coding_agent/src/extensions/mcp/MCP_TUTORIAL.md
packages/fox_coding_agent/src/extensions/mcp/__init__.py
packages/fox_coding_agent/src/extensions/mcp/client.py
packages/fox_coding_agent/src/extensions/mcp/config.py
packages/fox_coding_agent/src/extensions/mcp/extension.py
packages/fox_coding_agent/src/extensions/mcp/manager.py
packages/fox_coding_agent/src/extensions/memory/MEMORY_DESIGN.md
packages/fox_coding_agent/src/extensions/memory/MEMORY_TUTORIAL.md
packages/fox_coding_agent/src/extensions/memory/__init__.py
packages/fox_coding_agent/src/extensions/memory/eval.py
packages/fox_coding_agent/src/extensions/memory/extension.py
packages/fox_coding_agent/src/extensions/memory/fixtures/__init__.py
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/__init__.py
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/generate.py
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/manifest.json
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/queries.jsonl
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/results.json
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/__init__.py
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_api-689acd3d72.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-1652d1bc31.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-34eb530df1.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-43e9126221.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-6098570e47.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-932d8a7741.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-9ca0ae25af.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-a2f81c53c0.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/feedback_memory-f42d40d4df.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_api-6c23d4f848.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_api-92e50d5ecd.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_cli-3a90832771.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_feature-flag-8ae9807670.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_http-12c52c8d29.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-13a5ce2a34.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-2737a25cdc.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-30a954771b.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-353c84ad02.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-5deaf5f32e.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-69b10e0fca.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-9d069e69d5.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-be149f4e5f.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-bffaa5b68d.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-d6481f375c.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-d8f2fef959.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-f90d8c01ce.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-fd51da6ba1.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_memory-fdaf18bd1b.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_python-30ef84cb36.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_python-33e306429b.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_python-48af465261.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/project_staging-d4238274ac.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_api-schema-26cad9b690.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_memory-5352b962a3.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_memory-71ca9554ff.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_memory-a8bc79d479.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_memory-bde253af7d.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_memory-d29f562390.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_memory-ed94f3eb07.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_pydantic-4f711b7c22.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/reference_python-593df5a0ad.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-339467b50a.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-3d88452021.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-73e0f55500.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-9076c76cf0.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-97f509300f.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-adf8561851.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-d0c4fb82c6.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-e7ad55bb4f.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/store/user_memory-ebe4467f6a.md
packages/fox_coding_agent/src/extensions/memory/fixtures/memory_eval/write_cases.jsonl
packages/fox_coding_agent/src/extensions/memory/injection.py
packages/fox_coding_agent/src/extensions/memory/models.py
packages/fox_coding_agent/src/extensions/memory/retrieval.py
packages/fox_coding_agent/src/extensions/memory/store.py
packages/fox_coding_agent/src/extensions/skill_evolution/README.md
packages/fox_coding_agent/src/extensions/skill_evolution/TUTORIAL.md
packages/fox_coding_agent/src/extensions/skill_evolution/__init__.py
packages/fox_coding_agent/src/extensions/skill_evolution/extension.py
packages/fox_coding_agent/src/extensions/skill_evolution/extraction.py
packages/fox_coding_agent/src/extensions/skill_evolution/maintainer.py
packages/fox_coding_agent/src/extensions/skill_evolution/models.py
packages/fox_coding_agent/src/extensions/skill_evolution/online_eval.py
packages/fox_coding_agent/src/extensions/skill_evolution/retrieval.py
packages/fox_coding_agent/src/extensions/skill_evolution/store.py
packages/fox_coding_agent/src/extensions/subagent/SUBAGENT_DESIGN.md
packages/fox_coding_agent/src/extensions/subagent/SUBAGENT_TUTORIAL.md
packages/fox_coding_agent/src/extensions/subagent/__init__.py
packages/fox_coding_agent/src/extensions/subagent/discovery.py
packages/fox_coding_agent/src/extensions/subagent/extension.py
packages/fox_coding_agent/src/extensions/subagent/models.py
tests/test_agent_core.py
tests/test_architecture_refactor.py
tests/test_auth_models.py
tests/test_backend_refactor.py
tests/test_coding_agent.py
tests/test_harness_tools.py
tests/test_memory_eval.py
tests/test_memory_extension.py
tests/test_plan_mode.py
tests/test_runtime.py
tests/test_sandbox.py
tests/test_skill_evolution.py
tests/test_skill_experiment.py
tests/test_skill_online_eval.py
tests/test_streamed_write.py
tests/test_subagent_mcp_extensions.py
```
