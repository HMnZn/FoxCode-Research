# fox_agent_core

详细学习指南：[主循环、五个工具、Hook、取消与离线案例](../../docs/learning/AGENT_CORE.md) · [全栈学习索引](../../docs/learning/README.md)

![模型与工具循环](../../docs/learning/assets/agent-loop.svg)

极简 tool-using harness。User → Model → Tool Calls → Tool Results → Model，没有工具调用时结束。`agent_loop.py` 是主流程，`Agent` 保存 Context、忙碌状态和取消任务。

五个工具：Read（offset/limit/输出限制）、Write（UTF-8/父目录）、Edit（唯一精确匹配）、Glob（文件和目录发现）、Bash（cwd/timeout/stdout/stderr/returncode）。非零退出码变为失败 observation，取消/超时清理 shell 进程树。

Hooks 是五个可选 sync/async callback：before_model、after_model、before_tool、after_tool、on_run_end。工具异常回到模型，模型错误和轮数上限结束 run。中断时补齐失败 result，保留 call/result 配对。

Session、Memory、Skill、Compression 不在这一层。
验证：仓库根目录 `uv run python -m pytest tests/test_agent.py -q`。
