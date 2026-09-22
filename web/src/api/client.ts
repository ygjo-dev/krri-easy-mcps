// BFF 만 부른다. Gateway · MCP endpoint · agentic_ai 를 브라우저에서 직접 부르지 않는다.
import type { DemoQuestion, Execution, McpCard, McpDetail, Toolbox } from '../types/api'

// BFF 가 준 detail 문구만 싣는다 (BFF 가 이미 내부 정보를 걸러 낸 문구다).
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
  return res.json() as Promise<T>
}

export const api = {
  listMcps: () => request<McpCard[]>('/api/mcps'),
  getMcp: (serverId: string) => request<McpDetail>(`/api/mcps/${encodeURIComponent(serverId)}`),
  listDemoQuestions: (serverId: string) =>
    request<DemoQuestion[]>(`/api/mcps/${encodeURIComponent(serverId)}/demo-questions`),
  executeDemoQuestion: (questionId: string) =>
    request<Execution>(`/api/demo/questions/${encodeURIComponent(questionId)}/execute`, { method: 'POST' }),
  getToolbox: () => request<Toolbox>('/api/toolbox'),
  addToToolbox: (serverId: string) =>
    request<Toolbox>(`/api/toolbox/${encodeURIComponent(serverId)}`, { method: 'POST' }),
  removeFromToolbox: (serverId: string) =>
    request<Toolbox>(`/api/toolbox/${encodeURIComponent(serverId)}`, { method: 'DELETE' }),
}
