import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { request, run } from './api'
import type { ResearchState, StreamEvent, TimelineItem } from './types'
import { FoxMark, Icon } from './icons'

export function App() {
  const [state, setState] = useState<ResearchState>({ configured: false })
  const [items, setItems] = useState<TimelineItem[]>([])
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [status, setStatus] = useState('就绪')
  const [configOpen, setConfigOpen] = useState(false)
  const [connected, setConnected] = useState<boolean | null>(null)
  const [panel, setPanel] = useState<'context' | 'memory' | 'skills'>('context')
  const [memoryOpen, setMemoryOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [trial, setTrial] = useState('')
  const [memory, setMemory] = useState('')
  const [model, setModel] = useState('')
  const [cwd, setCwd] = useState('.')
  const [baseUrl, setBaseUrl] = useState('https://api.openai.com/v1')
  const [apiKey, setApiKey] = useState('')
  const [budget, setBudget] = useState(12000)
  const controller = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  const refresh = async () => {
    const next = await request<ResearchState>('state')
    setState(next)
    if (next.model) setModel(next.model)
    if (next.cwd) setCwd(next.cwd)
    if (next.base_url) setBaseUrl(next.base_url)
    setConnected(true)
    if (next.context?.budget) setBudget(next.context.budget)
  }
  useEffect(() => {
    void refresh().catch(e => { setConnected(false); setError(e instanceof Error ? e.message : String(e)) })
    return () => controller.current?.abort()
  }, [])
  useEffect(() => {
    const timeline = bottom.current?.parentElement
    if (timeline) timeline.scrollTop = timeline.scrollHeight
  }, [items])
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n'
        && state.configured && !busy && !configOpen) {
        event.preventDefault()
        void reset()
      }
    }
    document.addEventListener('keydown', shortcut)
    return () => document.removeEventListener('keydown', shortcut)
  }, [busy, state.configured, configOpen])

  async function saveConfig(event: FormEvent) {
    event.preventDefault()
    setError('')
    setSaving(true)
    try {
      const next = await request<ResearchState>('config', {
        model, cwd, base_url: baseUrl, api_key: apiKey || null, context_budget: budget,
      })
      setState(next); setConfigOpen(false); setApiKey(''); setItems([]); setTrial(''); setConnected(true); setStatus('就绪')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setSaving(false) }
  }

  async function send(event: FormEvent) {
    event.preventDefault()
    if (!prompt.trim() || busy) return
    const text = prompt
    setPrompt(''); setError(''); setBusy(true); setStatus('运行中')
    const prefix = crypto.randomUUID()
    let assistantId = ''
    let turn = 0
    setItems(old => [...old, { id: `${prefix}-user`, kind: 'user', text }])
    const receive = (event: StreamEvent) => {
      const data = event.data
      if (event.type === 'model_start') {
        assistantId = `${prefix}-model-${turn++}`
        const id = assistantId
        setItems(old => [...old, { id, kind: 'assistant', text: '', reasoning: '', pending: true }])
      } else if (event.type === 'text_delta' || event.type === 'thinking_delta') {
        const id = assistantId
        setItems(old => old.map(item => item.id !== id ? item : event.type === 'text_delta'
          ? { ...item, text: item.text + (data.delta ?? '') } : { ...item, reasoning: (item.reasoning ?? '') + (data.delta ?? '') }))
      } else if (event.type === 'model_end') {
        const id = assistantId
        setItems(old => old.map(item => item.id === id ? { ...item, pending: false } : item))
      } else if (event.type === 'tool_start' && data.call) {
        const call = data.call
        setItems(old => [...old, { id: `${prefix}-${call.id}`, kind: 'tool', text: '', call, pending: true }])
      } else if (event.type === 'tool_end' && data.call && data.result) {
        const id = `${prefix}-${data.call.id}`
        const result = data.result
        setItems(old => old.map(item => item.id === id
          ? { ...item, text: result.content, error: result.is_error, pending: false } : item))
      } else if (event.type === 'research_state') {
        setState({ configured: true, ...data } as ResearchState)
      } else if (event.type === 'error') {
        setError(data.error ?? '执行失败')
      } else if (event.type === 'run_end') {
        setStatus(data.status === 'completed' ? '已完成' : data.status === 'cancelled' ? '已停止' : '执行失败')
        setItems(old => old.map(item => item.pending ? {
          ...item, pending: false,
          error: item.kind === 'tool', text: item.kind === 'tool' ? '执行中断' : item.text
        } : item))
      }
    }
    controller.current = new AbortController()
    try { await run(text, trial, receive, controller.current.signal) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); setStatus('连接中断') }
    finally { setBusy(false); controller.current = null; void refresh().catch(e => { setConnected(false); setError(e instanceof Error ? e.message : String(e)) }) }
  }

  async function stop() {
    try { await request('stop', {}) } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function reset() {
    try {
      setState(await request<ResearchState>('reset', {})); setItems([]); setStatus('就绪'); setTrial('')
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function remember(event: FormEvent) {
    event.preventDefault()
    try { await request('memory', { content: memory }); setMemory(''); await refresh() }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }
  async function feedback(name: string, useful: boolean) {
    try {
      await request('skills/validate', { name, trajectory_id: state.trajectory_id, useful })
      await refresh()
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
  }

  const task = state.context?.state
  const tokens = state.context?.tokens ?? 0
  const tokenBudget = state.context?.budget ?? budget
  const memoryCount = Object.values(state.memory?.counts ?? {}).reduce((sum, n) => sum + n, 0)
  const skills = state.skills?.items ?? []
  const activeSkills = skills.filter(skill => ['active', 'mature'].includes(skill.status)).length
  const projectName = state.cwd?.split(/[\\/]/).filter(Boolean).at(-1) ?? '选择一个项目'
  const visibleItems = items.filter(item => item.kind !== 'assistant' || item.pending || item.text || item.reasoning)
  const examples = [
    { icon: 'code' as const, title: '理解项目', text: '梳理这个项目的结构与核心模块，解释代码执行流程。' },
    { icon: 'terminal' as const, title: '修复问题', text: '找到并修复失败的测试，说明问题原因并验证改动。' },
    { icon: 'spark' as const, title: '实现功能', text: '先阅读现有代码，再实现一个小功能并补充必要验证。' },
  ]

  function reconnect() {
    setError('')
    setConnected(null)
    void refresh().catch(e => { setConnected(false); setError(e instanceof Error ? e.message : String(e)) })
  }

  return <div className="app-shell">
    <nav className="sidebar" aria-label="主导航">
      <div className="brand">
        <FoxMark />
        <div>
          <strong>FoxCode<span>Research</span>
          </strong>
          <small>YOUR CODING COMPANION</small>
        </div>
      </div>
      <button className="new-task" onClick={reset} disabled={busy || !state.configured}>
        <Icon name="plus" />新任务<span>⌘ N</span>
      </button>
      <div className="nav-label">WORKSPACE</div>
      <button className={`nav-item ${panel === 'context' ? 'selected' : ''}`} onClick={() => setPanel('context')}>
        <Icon name="workspace" />任务工作区</button>
      <button className={`nav-item ${panel === 'memory' ? 'selected' : ''}`} onClick={() => setPanel('memory')}>
        <Icon name="memory" />项目记忆<span className="nav-count">{memoryCount}</span>
      </button>
      <button className={`nav-item ${panel === 'skills' ? 'selected' : ''}`} onClick={() => setPanel('skills')}>
        <Icon name="spark" />演化技能<span className="nav-count">{skills.length}</span>
      </button>
      <div className="project-card">
        <div className="nav-label">CURRENT PROJECT</div>
        <div>
          <Icon name="folder" />
          <strong>{projectName}</strong>
        </div>
        <p title={state.cwd}>{state.cwd ?? '配置目录，开始你的第一个任务'}</p>
      </div>
      <div className="sidebar-bottom">
        <div className="research-note">
          <Icon name="book" />
          <span>小而清晰的 Agent<br />
            <small>为阅读、探索与实验而生</small>
          </span>
        </div>
        <button className="connection" onClick={connected === false ? reconnect : () => setConfigOpen(true)}>
          <span className={`dot ${connected === false ? 'offline' : connected === null ? 'connecting' : ''}`} />
          <span>{connected === false ? '服务未连接' : connected === null ? '正在连接服务' : '本地服务已连接'}</span>
          <Icon name={connected === false ? 'retry' : 'settings'} />
        </button>
      </div>
    </nav>

    <div className="main-shell">
      <header className="topbar">
        <div className="breadcrumb">Workspace<Icon name="chevron" />
          <strong>任务工作区</strong>
          <span className="version-label">RESEARCH EDITION</span>
        </div>
        <button className="model-selector" onClick={() => setConfigOpen(true)} disabled={busy}>
          <span className={`dot ${state.configured ? '' : 'offline'}`} />
          <span>{state.model ?? '配置模型'}</span>
          <Icon name="settings" />
        </button>
      </header>
      {error && <div className="error-banner" role="alert">
        <Icon name="alert" />
        <div>
          <strong>{connected === false ? '暂时无法连接 Agent 服务' : '操作未完成'}</strong>
          <p>{error}</p>
        </div>{connected === false && <button onClick={reconnect}>
          <Icon name="retry" />重新连接</button>}<button className="icon-button" aria-label="关闭错误提示" onClick={() => setError('')}>
          <Icon name="close" />
        </button>
      </div>}

      <main className="main-grid">
        <section className="workspace">
          <div className="workspace-heading">
            <div>
              <span className="eyebrow">LET’S BUILD SOMETHING</span>
              <h2>{items.length ? '任务进行记录' : '你的代码，新的可能。'}</h2>
            </div>
            <span className={`run-status ${busy ? 'is-running' : ''}`}>
              <span className="dot" />{status}</span>
          </div>
          <div className={`timeline ${!items.length ? 'is-empty' : ''}`} aria-live="polite">
            {!items.length && <div className="welcome">
              <div className="welcome-art" aria-hidden="true">
                <div className="orbit orbit-one" />
                <div className="orbit orbit-two" />
                <span className="floating-symbol symbol-code">
                  <Icon name="code" />
                </span>
                <span className="floating-symbol symbol-memory">
                  <Icon name="memory" />
                </span>
                <span className="floating-symbol symbol-spark">
                  <Icon name="spark" />
                </span>
                <div className="fox-tile">
                  <FoxMark />
                </div>
                <span className="art-dot dot-one" />
                <span className="art-dot dot-two" />
              </div>
              <span className="welcome-kicker">A LITTLE FOX. A CLEARER WORKFLOW.</span>
              <h1>把想法交给 FoxCode</h1>
              <p>读懂代码、解决问题、验证改动。<br />每一次实践，都成为下一次的经验。</p>
              <div className="suggestions">{examples.map(example => <button key={example.title} onClick={() => setPrompt(example.text)} disabled={busy}>
                <span className="suggestion-icon">
                  <Icon name={example.icon} />
                </span>
                <strong>{example.title}</strong>
                <small>{example.title === '理解项目' ? '从架构与执行流程开始' : example.title === '修复问题' ? '定位原因，验证修复' : '遵循现有代码与约定'}</small>
                <Icon name="arrow" />
              </button>)}</div>
              {!state.configured && <button className="setup-hint" onClick={() => setConfigOpen(true)}>
                <Icon name="settings" />{connected === false ? '连接服务后，配置模型与项目目录' : '先配置模型与项目目录，准备开始'}<Icon name="arrow" />
              </button>}
            </div>}
            {visibleItems.map(item => <article key={item.id} className={`message ${item.kind}`}>
              <div className="message-avatar">{item.kind === 'user' ? '你' : item.kind === 'tool' ? <Icon name="terminal" /> : <FoxMark />}</div>
              <div className="message-body">
                <div className="message-label">
                  <strong>{item.kind === 'user' ? '你' : item.kind === 'tool' ? item.call?.name : 'FoxCode'}</strong>
                  <small>{item.pending ? '正在执行' : item.kind === 'tool' ? item.error ? '需要修正' : '执行完成' : item.kind === 'assistant' ? 'Coding agent' : '任务指令'}</small>
                </div>
                {item.reasoning && <details className="reasoning">
                  <summary>
                    <Icon name="spark" />思考过程</summary>
                  <pre>{item.reasoning}</pre>
                </details>}
                {item.kind === 'tool' ? <details className={`tool-card ${item.error ? 'tool-error' : ''}`} open={item.pending || item.error}>
                  <summary>
                    <Icon name={item.error ? 'alert' : item.pending ? 'terminal' : 'check'} />
                    <span>{String(item.call?.arguments.file_path ?? item.call?.arguments.command ?? item.call?.arguments.pattern ?? item.call?.name)}</span>
                    <span className="tool-state">{item.pending ? '运行中' : item.error ? '工具失败' : '工具结果'}</span>
                    <Icon name="chevron" />
                  </summary>
                  <div className="tool-content">
                    <span className="code-label">ARGUMENTS</span>
                    <pre>{JSON.stringify(item.call?.arguments, null, 2)}</pre>
                    <span className="code-label">OUTPUT</span>
                    <pre>{item.text}</pre>
                  </div>
                </details> : <div className="message-text">{item.text || (item.pending ? '正在思考…' : '')}</div>}
              </div>
            </article>)}
            <div ref={bottom} />
          </div>
          <div className="composer-wrap">
            <form className={`composer ${busy ? 'composer-busy' : ''}`} onSubmit={send}>
              {trial && <div className="trial">
                <Icon name="spark" />试用 Skill：{trial}<button type="button" className="icon-button" aria-label="取消试用" onClick={() => setTrial('')} disabled={busy}>
                  <Icon name="close" />
                </button>
              </div>}
              <textarea aria-label="任务 Prompt" value={prompt} onChange={e => setPrompt(e.target.value)} placeholder="描述你的代码任务，让我们一起完成…" disabled={busy} rows={3} onKeyDown={e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); e.currentTarget.form?.requestSubmit() } }} />
              <div className="composer-footer">
                <div className="composer-tools">
                  <span className="tool-pill">
                    <Icon name="code" />5 tools ready</span>
                  <span className="composer-project">
                    <Icon name="folder" />{projectName}</span>
                </div>{busy ? <button type="button" className="stop-button" onClick={stop}>
                  <Icon name="stop" />停止任务</button> : <button className="primary" disabled={!state.configured || !prompt.trim() || saving}>开始任务<Icon name="arrow" />
                </button>}</div>
            </form>
            <div className="composer-caption">
              <span>Read · Write · Edit · Glob · Bash</span>
              <span>⌘ / Ctrl + Enter 发送</span>
            </div>
          </div>
        </section>

        <aside className="inspector">
          <div className="inspector-heading">
            <div>
              <span className="eyebrow">BEHIND THE TASK</span>
              <h3>研究面板</h3>
            </div>
            <span className="live-label">
              <span className="dot" />LIVE</span>
          </div>
          <div className="inspector-tabs" role="tablist" aria-label="研究模块">{(['context', 'memory', 'skills'] as const).map(tab => <button key={tab} role="tab" aria-selected={panel === tab} onClick={() => setPanel(tab)}>{tab === 'context' ? 'Context' : tab === 'memory' ? 'Memory' : 'Skills'}</button>)}</div>
          <div className="inspector-content" role="tabpanel" aria-label={panel}>
            {panel === 'context' && <>
              <section className="research-card context-card">
                <div className="card-title">
                  <span className="module-icon">
                    <Icon name="workspace" />
                  </span>
                  <div>
                    <h4>上下文预算</h4>
                    <p>每次模型调用的信息窗口</p>
                  </div>
                </div>
                <div className="token-total">
                  <strong>{tokens.toLocaleString()}</strong>
                  <span>/ {tokenBudget.toLocaleString()} <small>tokens</small>
                  </span>
                </div>
                <div className="budget-track">
                  <div style={{ width: `${Math.min(100, tokens / tokenBudget * 100)}%` }} />
                </div>
                <div className="card-foot">
                  <span>已使用 {(tokens / tokenBudget * 100).toFixed(1)}%</span>
                  <span>压缩 {state.context?.compressions ?? 0} 次</span>
                </div>
              </section>
              <section className="research-card">
                <div className="card-title">
                  <Icon name="code" />
                  <h4>当前任务状态</h4>
                  <span className="small-badge">WORKING</span>
                </div>{task?.goal ? <>
                  <p className="goal">{task.goal}</p>{([['约束', task.constraints], ['计划', task.plan], ['重要文件', task.important_files], ['代码修改', task.changes], ['失败记录', task.failures], ['测试状态', task.tests]] as const).map(([label, values]) => values.length > 0 && <details key={label}>
                    <summary>{label}<span className="count-badge">{values.length}</span>
                    </summary>
                    <pre>{values.join('\n')}</pre>
                  </details>)}{task.working && <details>
                    <summary>当前工作状态</summary>
                    <pre>{task.working}</pre>
                  </details>}</> : <div className="panel-empty">
                  <span className="empty-mini">
                    <Icon name="folder" />
                  </span>
                  <p>等待第一个任务</p>
                  <small>目标、约束与代码改动<br />会在这里逐步清晰起来。</small>
                </div>}</section>
              <div className="insight-note">
                <Icon name="spark" />
                <p>保留目标与约束，压缩重复信息。<br />
                  <span>让有限上下文专注于当前任务。</span>
                </p>
              </div>
              <button className="module-summary" onClick={() => setPanel('memory')}>
                <Icon name="memory" />
                <span>项目记忆<small>{memoryCount} 条经验 · {state.memory?.retrieved.length ?? 0} 条已召回</small>
                </span>
                <Icon name="chevron" />
              </button>
              <button className="module-summary" onClick={() => setPanel('skills')}>
                <Icon name="spark" />
                <span>演化技能<small>{activeSkills} 个活跃 · {skills.filter(s => s.status === 'candidate').length} 个候选</small>
                </span>
                <Icon name="chevron" />
              </button>
            </>}
            {panel === 'memory' && <>
              <section className="research-card">
                <div className="card-title">
                  <Icon name="memory" />
                  <h4>项目长期记忆</h4>
                </div>
                <p className="panel-description">积累项目知识与实践经验，在需要时轻量召回。</p>
                <div className="memory-metrics">
                  <div>
                    <strong>{state.memory?.counts.episodic ?? 0}</strong>
                    <small>Episodic · 实践经验</small>
                  </div>
                  <div>
                    <strong>{state.memory?.counts.semantic ?? 0}</strong>
                    <small>Semantic · 项目知识</small>
                  </div>
                </div>
              </section>
              <div className="panel-section-label">本次召回<span>{state.memory?.retrieved.length ?? 0}</span>
              </div>{state.memory?.retrieved.length ? state.memory.retrieved.map((hit, i) => <details className="research-card" key={i}>
                <summary>{hit.memory.memory_type}<span className="small-badge">{hit.score.toFixed(2)}</span>
                </summary>
                <pre>{hit.memory.content}</pre>
                <small>{hit.memory.verify ? 'Historical hint · 使用前验证' : '项目偏好 / 经验'}</small>
              </details>) : <div className="panel-empty research-card">
                <span className="empty-mini">
                  <Icon name="book" />
                </span>
                <p>经验会随着任务积累</p>
                <small>相关记忆会在下一个任务开始时召回。</small>
              </div>}
              <button className="add-memory" onClick={() => setMemoryOpen(!memoryOpen)} disabled={!state.configured}>
                <Icon name="plus" />添加项目知识</button>{memoryOpen && <form className="memory-form research-card" onSubmit={remember}>
                  <label>值得长期保留的知识<textarea aria-label="项目记忆" value={memory} onChange={e => setMemory(e.target.value)} placeholder="例如：项目使用 uv 管理依赖，pytest 运行测试。" rows={4} />
                  </label>
                  <button className="primary" disabled={!memory.trim() || !state.configured}>保存记忆<Icon name="check" />
                  </button>
                </form>}
              <div className="insight-note">
                <Icon name="check" />
                <p>Verify before use<span>历史事实是线索，使用前验证当前状态。</span>
                </p>
              </div>
            </>}
            {panel === 'skills' && <>
              <section className="research-card">
                <div className="card-title">
                  <Icon name="spark" />
                  <h4>从经验到策略</h4>
                </div>
                <p className="panel-description">从失败与恢复中发现方法，通过独立任务验证，留下有效策略。</p>
                <div className="skill-lifecycle">
                  <span>Candidate</span>
                  <Icon name="arrow" />
                  <span>Active</span>
                  <Icon name="arrow" />
                  <span>Mature</span>
                </div>
              </section>
              {!skills.length && <div className="panel-empty research-card">
                <span className="empty-mini">
                  <Icon name="spark" />
                </span>
                <p>让实践成为能力</p>
                <small>遇到问题、调整方法、验证成功。<br />FoxCode 会从真实轨迹提炼候选 Skill。</small>
              </div>}
              {skills.map(skill => <details className="research-card skill-card" key={skill.name}>
                <summary>{skill.name}<span className={`badge badge-${skill.status}`}>{skill.status}</span>
                </summary>
                <p className="panel-description">{skill.trigger}</p>
                <pre>{skill.instructions}</pre>
                <div className="skill-evidence">
                  <span>v{skill.version}</span>
                  <span>{skill.success_count} 成功 / {skill.failure_count} 失败</span>
                  <span>U = {skill.utility}</span>
                </div>
                <div className="skill-actions">
                  <button onClick={() => setTrial(skill.name)} disabled={busy || ['rejected', 'pruned'].includes(skill.status)}>下次任务试用</button>
                  <button onClick={() => feedback(skill.name, true)} disabled={busy || !state.skills?.selected.includes(skill.name)}>有效</button>
                  <button onClick={() => feedback(skill.name, false)} disabled={busy || !state.skills?.selected.includes(skill.name)}>无效</button>
                </div>
              </details>)}
              <div className="insight-note">
                <Icon name="check" />
                <p>证据驱动的演化<span>候选策略不会因一次成功就永久启用。</span>
                </p>
              </div>
            </>}
          </div>
          <div className="inspector-footer">
            <span className="dot" />Context → Memory → Skill</div>
        </aside>
      </main>
    </div>

    {configOpen && <div className="modal-backdrop" onMouseDown={e => { if (e.target === e.currentTarget && !saving) setConfigOpen(false) }}>
      <section className="config-dialog" role="dialog" aria-modal="true" aria-labelledby="config-title" onKeyDown={e => {
        if (e.key === 'Escape' && !saving) setConfigOpen(false)
        if (e.key === 'Tab') {
          const fields = Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)'))
          const first = fields[0], last = fields.at(-1)
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
        }
      }}>
        <div className="dialog-heading">
          <div className="dialog-icon">
            <Icon name="settings" />
          </div>
          <div>
            <h2 id="config-title">准备你的工作环境</h2>
            <p>连接一个模型，选择一个项目，就可以开始。</p>
          </div>
          <button className="icon-button" aria-label="关闭配置" onClick={() => setConfigOpen(false)} disabled={saving}>
            <Icon name="close" />
          </button>
        </div>
        <form onSubmit={saveConfig}>
          <div className="config-fields">
            <label className="field-wide">项目目录<input autoFocus required value={cwd} onChange={e => setCwd(e.target.value)} placeholder="项目的绝对路径" />
              <small>Agent 将在此目录读取、修改代码与执行命令。</small>
            </label>
            <label>模型 ID<input required value={model} onChange={e => setModel(e.target.value)} placeholder="例如 deepseek-chat" />
            </label>
            <label>Context 预算<input type="number" min={512} max={28672} value={budget} onChange={e => setBudget(Number(e.target.value))} />
              <small>为模型输出留出空间。</small>
            </label>
            <label className="field-wide">API 地址<input required type="url" value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="https://your-endpoint/v1" />
              <small>OpenAI-compatible endpoint，通常以 /v1 结尾。</small>
            </label>
            <label className="field-wide">API Key <span className="optional-label">可选</span>
              <input type="password" autoComplete="off" value={apiKey} onChange={e => setApiKey(e.target.value)} placeholder="留空使用现有密钥或环境变量" />
              <small>密钥保留在服务端内存，不会回传到页面。</small>
            </label>
          </div>
          {error && <div className="dialog-error" role="alert">
            <Icon name="alert" />{error}</div>}
          <div className="dialog-footer">
            <span>
              <Icon name="code" />一个 adapter，多种兼容模型</span>
            <button type="button" onClick={() => setConfigOpen(false)} disabled={saving}>取消</button>
            <button className="primary" disabled={busy || saving || connected === false}>{saving ? '正在连接…' : '应用配置'}<Icon name="arrow" />
            </button>
          </div>
        </form>
      </section>
    </div>}
  </div>
}
