export type Skill = {
  name: string; description: string; trigger: string; instructions: string
  status: 'candidate' | 'active' | 'mature' | 'pruned' | 'rejected'
  success_count: number; failure_count: number; confidence: number; utility: number; version: number
}
export type ResearchState = {
  configured: boolean; model?: string; base_url?: string; cwd?: string; running?: boolean
  trajectory_id?: string | null
  context?: {
    tokens?: number; budget?: number; compressions?: number; state?: {
      goal: string; constraints: string[]; plan: string[]; important_files: string[]
      changes: string[]; failures: string[]; tests: string[]; working: string
    }
  }
  memory?: {
    counts: Record<string, number>; retrieved: {
      memory: { content: string; memory_type: string; verify: boolean }; score: number
    }[]
  }
  skills?: { selected: string[]; items: Skill[] }
}
export type ToolCall = { id: string; name: string; arguments: Record<string, unknown> }
export type StreamEvent = {
  type: string; data: {
    delta?: string; call?: ToolCall; result?: { content: string; is_error: boolean }
    status?: string; error?: string
  } & Partial<ResearchState>
}
export type TimelineItem = {
  id: string; kind: 'user' | 'assistant' | 'tool'; text: string
  reasoning?: string; call?: ToolCall; error?: boolean; pending?: boolean
}
