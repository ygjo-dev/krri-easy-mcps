// Browser ↔ BFF 응답 형태. app/api/services/*/*_router.py 와 맞춘다.

export type Status = 'online' | 'offline' | 'unknown'

// available   Gateway 에 있는 logical MCP (market group). status · tool_count 가 있다
// development 개발 중. Gateway 에 아직 없다. status · tool_count 가 null (0개 · 사용 불가가 아니다).
//             내 MCP 등록 · AI 실행 대상이 아니다
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

// MCP 가 KRRI-ASAP Data Library 에 제공하는 연결 데이터 (Gateway group layerDatasets 의 읽을 칸만)
export interface ConnectedDataset {
  name: string
  description: string
  // point | line | polygon | mixed | auto. 모르면 null
  geometry_kind: string | null
}

// long_description · tags · connected_datasets · updated_at 은 Gateway group 값이다 (개발 중이면 비어 있다).
// tools 는 Gateway /api/tools 값이다.
export interface McpDetail extends McpCard {
  long_description: string
  tags: string[]
  connected_datasets: ConnectedDataset[]
  // group server 들의 마지막 상태 확인 시각 (ISO). metadata 편집 시각이 아니다
  updated_at: string | null
  tools: Tool[]
}

export interface DemoQuestion {
  question_id: string
  display_text: string
  // EASY 「AI로 사용해보기」(agentic_ai)로 실행할 수 있는가. false 면 AI 에게 물어볼 때 참고할 예시만이다
  runnable: boolean
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

// 내 MCP. 브라우저는 mcp_id 만 안다 (Gateway selection 내부 표현은 BFF 가 숨긴다).
export interface Toolbox {
  mcp_ids: string[]
  mcps: McpCard[]
}

// EASY 자체 계정 (KRRI_ASAP 로그인과 별개). BFF 는 이름과 역할만 준다.
export type Role = 'USER' | 'ADMIN'

export interface AuthUser {
  username: string
  role: Role
}

// GET /api/auth/me · POST /api/auth/login · POST /api/auth/logout 의 응답. 로그인 안 했으면 user 가 null
export interface AuthState {
  user: AuthUser | null
}

// KRRI AI Skills (ADMIN 전용). Skill = ChatGPT · Claude 가 읽는 Agent Skills package (SKILL.md + 참고 파일).
// MCP 와 다른 기능이다.
export type SkillTarget = 'chatgpt' | 'claude' | 'source'

// 각 서비스에 그대로 올릴 수 있는지. false 면 detail.warnings 에 이유가 있다
export interface SkillCompat {
  chatgpt: boolean
  claude: boolean
}

export interface SkillCard {
  id: string
  title: string
  description: string
  version: string
  author: string
  tags: string[]
  compat: SkillCompat
  file_count: number
  // unix 초
  created_at: number
  updated_at: number
}

export interface SkillDetail extends SkillCard {
  // SKILL.md 의 package 안 경로 (올린 이름 그대로: SKILL.md 또는 skill.md)
  main_file: string
  // SKILL.md 원문 (frontmatter 포함, 앞부분만)
  skill_md: string
  files: { path: string; size: number }[]
  // examples/ 폴더의 텍스트 파일
  examples: { path: string; content: string }[]
  warnings: string[]
  created_by: string
}

export interface CreateSkillInput {
  id: string
  title: string
  description: string
  version: string
  author: string
  tags: string[]
  instructions: string
  example: string
}

// ZIP 업로드 때 화면 표시 정보. 비우면 SKILL.md frontmatter metadata (또는 이전 버전 값)
export interface SkillUploadMeta {
  title?: string
  version?: string
  author?: string
  tags?: string
}
