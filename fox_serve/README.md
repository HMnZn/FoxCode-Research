# fox_serve

本地单 Agent HTTP/SSE，`uv run python -m fox_serve` 默认监听 `127.0.0.1:8877`。未配置模型时可从界面完成配置。

| Endpoint | 用途 |
| --- | --- |
| GET `/api/state` | 模型、Context、Memory、Skills |
| POST `/api/config` | `{model,base_url,cwd,api_key?,context_budget?}` |
| POST `/api/run` | `{prompt,trial_skill?,learn?}`，返回 SSE；显式 trial 默认不沉淀新知识 |
| POST `/api/stop` | 取消并等待当前任务 |
| POST `/api/reset` | 新任务，保留项目研究数据 |
| POST `/api/memory` | `{content,memory_type?,verify?,key?,ttl_days?}`，同项目/key 事实修订 |
| POST `/api/memory/invalidate` | `{id,reason}`，保留旧记录和失效原因 |
| POST `/api/skills/validate` | `{name,trajectory_id,useful,saved_calls?}` |
| GET `/api/skills/{name}/history` | 修订内容和来源事件 |
| POST `/api/skills/rollback` | `{name,version,reason}`，切换到已验证版本 |

SSE 每帧为 `data: {"type":"text_delta","data":{"delta":"..."}}` 加两个换行。
其余事件：model_start/end、thinking_delta、tool_call_delta、tool_start/end、research_state、error、run_start/end。
run_end 给出 completed/cancelled/error。同一时间一个任务，运行中重入/切配置/重置返回 409。断开流会取消任务，停止请求保留流连接以接收结束状态。

`desktop/dist` 存在时由同一服务提供页面；开发通过 Vite `/api` proxy 访问。
`tests/test_server.py` 覆盖真实 HTTP 流式到达、取消及 SDK→工具→SSE 链路。

Skill 反馈来自外部评估或人工，不在服务内判断效果。反馈只更新轨迹实际注入的版本，召回/注入计数不等于采用或有效。`GET /api/state` 还提供预算分层和压缩决策、记忆评分拆解/过期文件、最新候选和稳定版本。

`learn:false` 会关闭本次 Memory/Skill 沉淀及延迟纠正消费，仍保留原始轨迹、Context 与注入统计。普通任务默认学习，显式 `trial_skill` 默认关闭学习；可显式传 `learn:true` 改变这个行为。它是评估侧可用的隔离开关，不能替代冻结数据集与任务切分。
