# FoxCode 架构重构

本轮允许 breaking changes，整体收敛为 `fox_coding_agent → fox_agent_core → fox_ai`。
移除旧 provider/session/extension/sandbox 框架，统一 HTTP/SSE 和研究单页。

完整删除与合并清单、目录、规模和验证结果见 [重构报告](../docs/REFACTOR_REPORT.md)。
设计与边界见 [架构说明](../docs/ARCHITECTURE.md)。
