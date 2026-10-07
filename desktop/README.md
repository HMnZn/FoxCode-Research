# FoxCode Research Workspace

React 单页，原生 fetch 读取 POST SSE。`App.tsx` 保存页面状态，`api.ts` 处理 HTTP/SSE 分帧，`types.ts` 定义页面数据，没有 store/service/IPC 层。

先在仓库根目录执行 `uv sync`，再在本目录：

```bash
npm install
npm run dev
```

`npm run dev` 会同时启动 Python 服务（8877）和 Vite（默认 5273）。已运行的 Python 服务会直接复用；Vite 端口被占用时自动尝试 5274 等后续端口。`npm run dev:web` 只启动 Vite，也会自动选择可用端口。

打开终端输出的 `Local` 地址（默认 `http://127.0.0.1:5273`）。`npm run build` 后可从 Python 服务的 `http://127.0.0.1:8877` 访问。
`npm start` 启动薄 Electron 窗口，加载已有 HTTP 服务；`FOXCODE_UI_URL` 可改变地址。

支持配置、Prompt、流式文本/Thinking、工具参数与结果、停止、新任务、Context/Memory/Skill 状态、候选 Skill 试用与有效/无效反馈。状态来自真实服务，没有离线 Mock 回退。

`npm test` 验证 SSE、UTF-8、错误、工具显示和停止；`npm run build` 包含 TypeScript 检查。

浅色三栏工作台：左侧项目导航，中间任务、工具轨迹和 Prompt，右侧 Context / Memory / Skills 标签页。模型配置使用弹窗。支持 Ctrl/Cmd+Enter 发送、Ctrl/Cmd+N 新任务、小屏布局和减少动画偏好。
