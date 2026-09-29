// Browser ↔ BFF 응답 형태. api/app/routes 와 맞춘다.

export type Status = 'online' | 'offline' | 'unknown'

// available   Gateway 에 있는 logical MCP (market group). status · tool_count 가 있다
// development 개발 중. Gateway 에 아직 없다. status · tool_count 가 null (0개 · 사용 불가가 아니다).
//             도구함 등록 · AI 실행 대상이 아니다
export type Lifecycle = 'available' | 'development'

// MCP 하나 = logical MCP (mcp_id). physical server 는 BFF 안의 구현 세부라 여기에 없다.
export interface McpCard {
  mcp_id: string
  display_name: string
  summary: string
  category: string
  organization: string
  lifecycle: Lifecycle
  status: Status | null
  tool_count: number | null
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
  // 그 Tool 을 가진 logical MCP 이름. 한 질문이 여러 MCP 의 Tool 을 쓸 수 있다. 모르면 null
  mcp_name: string | null
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

// 도구함. 브라우저는 mcp_id 만 안다 (Gateway selection 내부 표현은 BFF 가 숨긴다).
export interface Toolbox {
  mcp_ids: string[]
  mcps: McpCard[]
}
