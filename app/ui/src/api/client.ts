// BFF 만 부른다. Gateway · MCP endpoint · agentic_ai 를 브라우저에서 직접 부르지 않는다.
import type {
  AuthState,
  CreateSkillInput,
  DemoQuestion,
  Execution,
  McpCard,
  McpDetail,
  SkillAnalysis,
  SkillCard,
  SkillDetail,
  SkillInfoUpdate,
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

// ZIP 은 올라갔지만 공유 정보 저장(PATCH)에 실패했다. Skill 은 이미 library 에 있다
export class ShareIncompleteError extends ApiError {
  skill: SkillDetail
  constructor(skill: SkillDetail, cause: ApiError) {
    super(cause.status, `Skill 은 등록했지만 공유 정보를 저장하지 못했습니다 (${cause.message}). 상세 화면에서 다시 수정하세요.`)
    this.skill = skill
  }
}

// 공유 정보 칸이 없는 응답(칸을 더하기 전 BFF)도 그릴 수 있게 기본값을 채운다
function withShareInfo<T extends SkillCard>(skill: T): T {
  const s: Partial<SkillCard> = skill
  return {
    ...skill,
    summary: s.summary ?? null,
    use_cases: s.use_cases ?? [],
    recommended_for: s.recommended_for ?? null,
    example_prompts: s.example_prompts ?? [],
    enrichment_source: s.enrichment_source ?? null,
  }
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
  listSkills: async () => (await request<SkillCard[]>('/api/skills')).map(withShareInfo),
  getSkill: async (skillId: string) => withShareInfo(await request<SkillDetail>(skillPath(skillId))),
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
  // AI 자동 정리. 서버가 package 를 검증하고 텍스트만 AI 에게 보낸다. 저장하지 않는다
  analyzeSkill: (file: File) =>
    request<SkillAnalysis>('/api/skills/analyze', { method: 'POST', headers: { 'Content-Type': 'application/zip' }, body: file }),
  reanalyzeSkill: (skillId: string) => request<SkillAnalysis>(skillPath(skillId, '/analyze'), { method: 'POST' }),
  updateSkillInfo: (skillId: string, info: SkillInfoUpdate) =>
    request<SkillDetail>(skillPath(skillId), {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(info),
    }),
  // 검토한 정보로 ZIP 공유: 기존 업로드(이름 · 버전 · 작성자) 다음에 나머지 표시 정보를 저장한다. package 는 올린 그대로다
  createSkillFromPackage: async (
    file: File,
    info: SkillInfoUpdate & { title: string; version: string; author: string },
  ): Promise<SkillDetail> => {
    const { title, version, author, ...rest } = info
    const created = await api.uploadSkill(file, { title, version, author })
    try {
      return await api.updateSkillInfo(created.id, rest)
    } catch (e) {
      throw new ShareIncompleteError(created, e as ApiError)
    }
  },
  // 내려받기만 한다. ChatGPT · Claude 에 설치하는 것이 아니다
  downloadSkill: async (skillId: string, target: SkillTarget) => {
    const res = await send(skillPath(skillId, `/download?target=${target}`))
    return { blob: await res.blob(), filename: attachmentName(res, `${skillId}-${target}.zip`) }
  },
}
