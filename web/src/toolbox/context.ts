import { createContext, useContext } from 'react'
import type { McpCard } from '../types/api'

export interface ToolboxState {
  // null = 아직 못 읽음 (불러오는 중이거나 실패)
  registered: Set<string> | null
  mcps: McpCard[]
  loadError: string | null
  pending: Set<string>
  errors: Record<string, string>
  add: (serverId: string) => Promise<void>
  remove: (serverId: string) => Promise<void>
}

export const ToolboxContext = createContext<ToolboxState | null>(null)

export function useToolbox(): ToolboxState {
  const value = useContext(ToolboxContext)
  if (!value) throw new Error('ToolboxProvider 밖에서 useToolbox 를 불렀습니다.')
  return value
}
