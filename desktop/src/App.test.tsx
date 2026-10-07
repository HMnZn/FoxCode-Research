import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { App } from './App'
import { request, run } from './api'
import type { StreamEvent } from './types'

vi.mock('./api', () => ({ request: vi.fn(), run: vi.fn() }))
beforeEach(() => {
  vi.mocked(request).mockReset()
  vi.mocked(run).mockReset()
  vi.mocked(request).mockResolvedValue({
    configured: true, model: 'qwen', cwd: 'project',
    context: { tokens: 123, budget: 12000 }, memory: { counts: { semantic: 2 }, retrieved: [] },
    skills: { selected: [], items: [] }
  })
})

it('sends prompt, renders streamed text/tools and research state', async () => {
  vi.mocked(run).mockImplementation(async (_prompt, _trial, receive) => {
    const events: StreamEvent[] = [
      { type: 'model_start', data: {} }, { type: 'text_delta', data: { delta: '检查项目' } },
      { type: 'tool_start', data: { call: { id: 'a', name: 'Read', arguments: { file_path: 'main.py' } } } },
      { type: 'tool_end', data: { call: { id: 'a', name: 'Read', arguments: {} }, result: { content: 'print(42)', is_error: false } } },
      { type: 'model_start', data: {} }, { type: 'text_delta', data: { delta: '任务完成' } },
      { type: 'run_end', data: { status: 'completed' } },
    ]
    events.forEach(receive)
  })
  render(<App />)
  await screen.findByText('qwen')
  fireEvent.change(screen.getByLabelText('任务 Prompt'), { target: { value: '修复 main.py' } })
  fireEvent.click(screen.getByRole('button', { name: '开始任务' }))
  await screen.findByText('任务完成')
  expect(screen.getByText('检查项目')).toBeTruthy()
  expect(screen.getByText('print(42)')).toBeTruthy()
  expect(screen.getByText('已完成')).toBeTruthy()
  expect(vi.mocked(run).mock.calls[0][0]).toBe('修复 main.py')
})

it('stops an active task without dropping the event connection', async () => {
  let finish: (() => void) | undefined
  vi.mocked(run).mockImplementation(async (_prompt, _trial, receive) => {
    await new Promise<void>(resolve => { finish = resolve })
    receive({ type: 'run_end', data: { status: 'cancelled' } })
  })
  render(<App />)
  await screen.findByText('qwen')
  fireEvent.change(screen.getByLabelText('任务 Prompt'), { target: { value: 'wait' } })
  fireEvent.click(screen.getByRole('button', { name: '开始任务' }))
  fireEvent.click(await screen.findByText('停止任务'))
  await waitFor(() => expect(request).toHaveBeenCalledWith('stop', {}))
  finish?.()
  await screen.findByText('已停止')
})

it('keeps setup in a dialog and sends explicit model configuration', async () => {
  vi.mocked(request).mockResolvedValueOnce({ configured: false })
  render(<App />)
  await screen.findByText('本地服务已连接')
  expect(screen.queryByRole('dialog')).toBeNull()
  fireEvent.click(screen.getByRole('button', { name: '配置模型' }))
  expect(screen.getByRole('dialog')).toBeTruthy()
  fireEvent.change(screen.getByLabelText('模型 ID'), { target: { value: 'deepseek-chat' } })
  fireEvent.click(screen.getByRole('button', { name: '应用配置' }))
  await waitFor(() => expect(request).toHaveBeenCalledWith('config', expect.objectContaining({ model: 'deepseek-chat' })))
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
})

it('reconnects after a service failure and switches research panels', async () => {
  vi.mocked(request).mockRejectedValueOnce(new Error('Python 服务未启动'))
  render(<App />)
  await screen.findByText('暂时无法连接 Agent 服务')
  fireEvent.click(screen.getByRole('button', { name: '重新连接' }))
  await screen.findByText('qwen')
  expect(screen.queryByRole('alert')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: 'Memory' }))
  expect(screen.getByText('项目长期记忆')).toBeTruthy()
  fireEvent.click(screen.getByRole('tab', { name: 'Skills' }))
  expect(screen.getByText('从经验到策略')).toBeTruthy()
})
