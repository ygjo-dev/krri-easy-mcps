import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Toolbox } from '../types/api'
import { ToolboxContext, type ToolboxState } from './context'

// 도구함 상태 한 벌. Catalog · Detail · 도구함 화면이 같은 값을 본다.
// 성공 응답(BFF 가 돌려준 실제 selection)으로만 바꾼다. 실패하면 이전 상태를 그대로 둔다.
export default function ToolboxProvider({ children }: { children: ReactNode }) {
  const [toolbox, setToolbox] = useState<Toolbox | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pending, setPending] = useState<Set<string>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    api.getToolbox().then(setToolbox, (e: Error) => setLoadError(e.message))
  }, [])

  const change = useCallback(async (serverId: string, call: (id: string) => Promise<Toolbox>) => {
    setPending((p) => new Set(p).add(serverId))
    setErrors((prev) => {
      const next = { ...prev }
      delete next[serverId]
      return next
    })
    try {
      setToolbox(await call(serverId))
      setLoadError(null)
    } catch (e) {
      setErrors((prev) => ({ ...prev, [serverId]: (e as Error).message }))
    } finally {
      setPending((p) => {
        const next = new Set(p)
        next.delete(serverId)
        return next
      })
    }
  }, [])

  const value = useMemo<ToolboxState>(
    () => ({
      registered: toolbox ? new Set(toolbox.server_ids) : null,
      mcps: toolbox?.mcps ?? [],
      loadError,
      pending,
      errors,
      add: (id) => change(id, api.addToToolbox),
      remove: (id) => change(id, api.removeFromToolbox),
    }),
    [toolbox, loadError, pending, errors, change],
  )

  return <ToolboxContext.Provider value={value}>{children}</ToolboxContext.Provider>
}
