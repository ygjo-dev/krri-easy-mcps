// Browser ↔ BFF 응답 형태. api/app/routes 와 맞춘다.

export type Status = 'online' | 'offline' | 'unknown'

export interface McpCard {
  server_id: string
  technical_name: string
  display_name: string
  summary: string
  category: string
  organization: string
  status: Status
  tool_count: number
  source: string
}

export interface ToolParameter {
  name: string
  type: string
  required: boolean
  description: string
  default: unknown
  enum: string[] | null
}

export interface Tool {
  name: string
  description: string
  parameters: ToolParameter[]
}

export interface McpDetail extends McpCard {
  tools: Tool[]
}

export interface DemoQuestion {
  question_id: string
  display_text: string
}

export interface ExecutionStep {
  node: string
  tool: string
  status: 'success' | 'failed'
  request: unknown
  response: unknown
}

export interface Execution {
  question_id: string
  display_text: string
  source: string
  resolve_status: string | null
  matches_expected_recipe: boolean | null
  matches_expected_tools: boolean | null
  steps: ExecutionStep[]
  answer: string
  map_command_count: number
  limitations: string[]
}

// 도구함. 브라우저는 server_id 만 안다 (Gateway selection 내부 표현은 BFF 가 숨긴다).
export interface Toolbox {
  server_ids: string[]
  mcps: McpCard[]
}
