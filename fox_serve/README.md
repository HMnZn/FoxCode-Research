# fox_serve

本地单 Agent HTTP/SSE，`uv run python -m fox_serve` 默认监听 `127.0.0.1:8877`。未配置模型时可从界面完成配置。

| Endpoint | 用途 |
| --- | --- |
| GET `/api/state` | 模型、Context、Memory、Skills |
| POST `/api/config` | `{model,base_url,cwd,api_key?,context_budget?}` |
| POST `/api/run` | `{prompt,trial_skill?}`，返回 SSE |
| POST `/api/stop` | 取消并等待当前任务 |
| POST `/api/reset` | 新任务，保留项目研究数据 |
| POST `/api/memory` | `{content,memory_type?,verify?}` |
| POST `/api/skills/validate` | `{name,trajectory_id,useful,saved_calls?}` |

SSE 每帧为 `data: {"type":"text_delta","data":{"delta":"..."}}` 加两个换行。
其余事件：model_start/end、thinking_delta、tool_call_delta、tool_start/end、research_state、error、run_start/end。
run_end 给出 completed/cancelled/error。同一时间一个任务，运行中重入/切配置/重置返回 409。断开流会取消任务，停止请求保留流连接以接收结束状态。

`desktop/dist` 存在时由同一服务提供页面；开发通过 Vite `/api` proxy 访问。
`tests/test_server.py` 覆盖真实 HTTP 流式到达、取消及 SDK→工具→SSE 链路。
