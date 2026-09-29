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

  const load = useCallback(() => {
    api.getToolbox().then(
      (t) => {
        setToolbox(t)
        setLoadError(null)
      },
      (e: Error) => setLoadError(e.message),
    )
  }, [])

  // load 를 그대로 넘기지 않는다. 반환값이 cleanup 자리로 가지 않게 block body 로 감싼다.
  useEffect(() => {
    load()
  }, [load])

  const change = useCallback(async (mcpId: string, call: (id: string) => Promise<Toolbox>) => {
    setPending((p) => new Set(p).add(mcpId))
    setErrors((prev) => {
      const next = { ...prev }
      delete next[mcpId]
      return next
    })
    try {
      setToolbox(await call(mcpId))
      setLoadError(null)
    } catch (e) {
      setErrors((prev) => ({ ...prev, [mcpId]: (e as Error).message }))
    } finally {
      setPending((p) => {
        const next = new Set(p)
        next.delete(mcpId)
        return next
      })
    }
  }, [])

  const value = useMemo<ToolboxState>(
    () => ({
      registered: toolbox ? new Set(toolbox.mcp_ids) : null,
      mcps: toolbox?.mcps ?? [],
      loadError,
      pending,
      errors,
      add: (id) => change(id, api.addToToolbox),
      remove: (id) => change(id, api.removeFromToolbox),
      reload: load,
    }),
    [toolbox, loadError, pending, errors, change, load],
  )

  return <ToolboxContext.Provider value={value}>{children}</ToolboxContext.Provider>
}
