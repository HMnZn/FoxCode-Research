export type Skill = {
  name: string; description: string; trigger: string; instructions: string
  status: 'candidate' | 'active' | 'mature' | 'pruned' | 'rejected'
  success_count: number; failure_count: number; confidence: number; utility: number; version: number
  champion_version?: number | null; confidence_lower?: number; retrieved_count?: number; injected_count?: number
  preconditions?: string[]; verification?: string[]; anti_patterns?: string[]
}
export type ResearchState = {
  configured: boolean; model?: string; base_url?: string; cwd?: string; running?: boolean
  trajectory_id?: string | null
  context?: {
    tokens?: number; budget?: number; compressions?: number; calibration?: number
    layers?: Record<string, number>; compacted_groups?: number; dropped_groups?: number
    decisions?: { group: number; action: string; utility: number; tokens: number; reason: string }[]
    retrieval_dropped?: {kind: string; id: string}[]; state?: {
      goal: string; constraints: string[]; plan: string[]; important_files: string[]
      changes: string[]; failures: string[]; tests: string[]; working: string
      failure_cases?: {call_id: string; status: string; error: string}[]
    }
  }
  memory?: {
    counts: Record<string, number>; statuses?: Record<string, number>; evidence_count?: number; retrieved: {
      memory: { content: string; memory_type: string; verify: boolean; id?: number; version?: number }
      score: number; breakdown?: Record<string, number>; stale_paths?: string[]; diversity_penalty?: number
    }[]
  }
  skills?: { selected: string[]; items: Skill[]
    evolution?: {pending_scopes: number; decisions: {action: string; name: string; reason: string; version?: number}[]}
  }
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
