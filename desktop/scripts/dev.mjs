// One command starts the local agent service and the renderer.
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../../', import.meta.url))
let backend
let vite
let stopping = false

async function ready() {
  try {
    const response = await fetch('http://127.0.0.1:8877/api/state', { signal: AbortSignal.timeout(1000) })
    return response.ok && typeof (await response.json()).configured === 'boolean'
  } catch { return false }
}

function stop(code = 0) {
  if (stopping) return
  stopping = true
  if (backend && backend.exitCode === null) {
    if (process.platform === 'win32') spawn('taskkill', ['/PID', String(backend.pid), '/T', '/F'], { stdio: 'ignore' })
    else backend.kill('SIGTERM')
  }
  void vite?.close()
  process.exitCode = code
}
process.on('SIGINT', () => stop())
process.on('SIGTERM', () => stop())

try {
  if (!await ready()) {
    console.log('Starting FoxCode agent service…')
    backend = spawn(process.env.FOXCODE_UV_CMD || 'uv', ['run', 'python', '-m', 'fox_serve'],
      { cwd: root, stdio: 'inherit', env: { ...process.env, PYTHONUNBUFFERED: '1' } })
    let startupError
    backend.on('error', error => { startupError = error })
    backend.on('exit', code => { if (vite && !stopping) stop(code || 1) })
    let started = false
    for (let attempt = 0; attempt < 120 && !stopping; attempt++) {
      if (startupError) throw new Error('uv 未找到，请先安装 uv 或设置 FOXCODE_UV_CMD。')
      if (backend.exitCode !== null) throw new Error('Agent 服务启动失败，请查看上方 Python 输出。')
      if (await ready()) { started = true; break }
      await new Promise(resolve => setTimeout(resolve, 500))
    }
    if (!started) throw new Error('Agent 服务启动超时，请运行 uv sync 后重试。')
  }
  if (!stopping) {
    vite = await createServer()
    await vite.listen()
    vite.printUrls()
  }
} catch (error) {
  console.error(error.message)
  stop(1)
}
