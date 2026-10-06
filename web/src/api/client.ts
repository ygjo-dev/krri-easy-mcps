// BFF 만 부른다. Gateway · MCP endpoint · agentic_ai 를 브라우저에서 직접 부르지 않는다.
import type {
  AuthState,
  CreateSkillInput,
  DemoQuestion,
  Execution,
  McpCard,
  McpDetail,
  SkillCard,
  SkillDetail,
  SkillTarget,
  SkillUploadMeta,
  Toolbox,
} from '../types/api'

// BFF 가 준 detail 문구만 싣는다 (BFF 가 이미 내부 정보를 걸러 낸 문구다).
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError(0, '서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    const fallback = res.status >= 500 ? '서버에 연결하지 못했습니다. 잠시 후 다시 시도하세요.' : '요청을 처리하지 못했습니다.'
    const detail = typeof body?.detail === 'string' ? body.detail : fallback
    throw new ApiError(res.status, detail)
  }
  return res
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await send(path, init)
  return (res.status === 204 ? undefined : res.json()) as Promise<T>
}

function skillPath(skillId: string, rest = '') {
  return `/api/skills/${encodeURIComponent(skillId)}${rest}`
}

function zipRequest(file: File, meta: SkillUploadMeta, method: 'POST' | 'PUT'): RequestInit & { query: string } {
  const query = new URLSearchParams(Object.entries(meta).filter(([, v]) => v && v.trim()) as [string, string][])
  return { method, headers: { 'Content-Type': 'application/zip' }, body: file, query: query.toString() }
}

// Content-Disposition 의 파일 이름. 못 읽으면 fallback
function attachmentName(res: Response, fallback: string): string {
  const header = res.headers.get('Content-Disposition') ?? ''
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(header)
  if (encoded) return decodeURIComponent(encoded[1])
  const plain = /filename="([^"]+)"/i.exec(header)
  return plain ? plain[1] : fallback
}

export const api = {
  listMcps: () => request<McpCard[]>('/api/mcps'),
  getMcp: (mcpId: string) => request<McpDetail>(`/api/mcps/${encodeURIComponent(mcpId)}`),
  listDemoQuestions: (mcpId: string) =>
    request<DemoQuestion[]>(`/api/mcps/${encodeURIComponent(mcpId)}/demo-questions`),
  executeDemoQuestion: (questionId: string) =>
    request<Execution>(`/api/demo/questions/${encodeURIComponent(questionId)}/execute`, { method: 'POST' }),
  getToolbox: () => request<Toolbox>('/api/toolbox'),
  addToToolbox: (mcpId: string) =>
    request<Toolbox>(`/api/toolbox/${encodeURIComponent(mcpId)}`, { method: 'POST' }),
  removeFromToolbox: (mcpId: string) =>
    request<Toolbox>(`/api/toolbox/${encodeURIComponent(mcpId)}`, { method: 'DELETE' }),
  // EASY 자체 로그인. 세션은 HttpOnly cookie 라 브라우저 코드는 token 을 보지 않는다.
  me: () => request<AuthState>('/api/auth/me'),
  login: (username: string, password: string) =>
    request<AuthState>('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    }),
  logout: () => request<AuthState>('/api/auth/logout', { method: 'POST' }),
  // KRRI AI Skills. 서버가 ADMIN 인지 검사한다 (비로그인 401 · ADMIN 아님 403).
  listSkills: () => request<SkillCard[]>('/api/skills'),
  getSkill: (skillId: string) => request<SkillDetail>(skillPath(skillId)),
  createSkill: (input: CreateSkillInput) =>
    request<SkillDetail>('/api/skills', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(input),
    }),
  // ZIP 은 multipart 가 아니라 body 그대로 보낸다
  uploadSkill: (file: File, meta: SkillUploadMeta) => {
    const { query, ...init } = zipRequest(file, meta, 'POST')
    return request<SkillDetail>(`/api/skills/upload${query ? `?${query}` : ''}`, init)
  },
  uploadSkillVersion: (skillId: string, file: File, meta: SkillUploadMeta) => {
    const { query, ...init } = zipRequest(file, meta, 'PUT')
    return request<SkillDetail>(skillPath(skillId, `/package${query ? `?${query}` : ''}`), init)
  },
  deleteSkill: (skillId: string) => request<void>(skillPath(skillId), { method: 'DELETE' }),
  // 내려받기만 한다. ChatGPT · Claude 에 설치하는 것이 아니다
  downloadSkill: async (skillId: string, target: SkillTarget) => {
    const res = await send(skillPath(skillId, `/download?target=${target}`))
    return { blob: await res.blob(), filename: attachmentName(res, `${skillId}-${target}.zip`) }
  },
}
