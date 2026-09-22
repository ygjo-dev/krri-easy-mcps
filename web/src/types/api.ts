// Browser ↔ BFF 응답 형태. api/app/routes 와 맞춘다.

export type Status = 'online' | 'offline' | 'unknown'

export interface McpCard {
  server_id: string
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

export interface InspectResult {
  source: string
  endpoint: string
  server_info: { name: string; version: string }
  protocol_version: string
  capabilities: Record<string, unknown>
  tools: { name: string; description: string; input_schema: unknown }[]
}
