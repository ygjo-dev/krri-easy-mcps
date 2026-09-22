// BFF 만 부른다. Gateway · MCP endpoint · agentic_ai 를 브라우저에서 직접 부르지 않는다.
import type { DemoQuestion, Execution, McpCard, McpDetail, Toolbox } from '../types/api'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail ?? `요청 실패 (${res.status})`)
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
