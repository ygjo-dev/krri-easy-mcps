import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { Toolbox } from '../types/api'
import { ToolboxContext, type ToolboxState } from './context'
import { subscribeToolboxChanges } from './selectionEvents'

// 도구함 상태 한 벌. Catalog · Detail · 도구함 화면이 같은 값을 본다.
// 성공 응답(BFF 가 돌려준 실제 selection)으로만 바꾼다. 실패하면 이전 상태를 그대로 둔다.
export default function ToolboxProvider({ children }: { children: ReactNode }) {
  const [toolbox, setToolbox] = useState<Toolbox | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [pending, setPending] = useState<Set<string>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})
  // 마지막으로 반영한 응답. 같은 응답이면 state 를 다시 쓰지 않는다.
  const shownRef = useRef('')
  // 등록 · 해제가 진행 중인 수와 그 차례. 그 사이에 떠난 다시 읽기의 응답은 버린다(옛 값으로 되돌리지 않게).
  const changingRef = useRef(0)
  const changeSeqRef = useRef(0)

  const show = useCallback((t: Toolbox) => {
    const json = JSON.stringify(t)
    if (json !== shownRef.current) {
      shownRef.current = json
      setToolbox(t)
    }
    setLoadError(null)
  }, [])

  const load = useCallback(
    () => api.getToolbox().then(show, (e: Error) => setLoadError(e.message)),
    [show],
  )

  // 처음 한 번 읽는다. 다른 화면(KRRI-ASAP 등)이 같은 selection 을 바꾸면 신호가 온다(BFF 가 Gateway 신호를 그대로 넘긴다).
  // 받으면, 그리고 다시 보이게 · focus 될 때 한 번 다시 읽는다. 반복 조회는 하지 않는다.
  // 읽는 중에 온 신호는 끝난 뒤 한 번 더 읽는다. 다시 읽기가 실패하면 조용히 넘긴다 — 화면은 마지막 값 그대로다.
  useEffect(() => {
    let reading = false
    let again = false
    let active = true
    let unsubscribe: (() => void) | undefined
    const refresh = () => {
      if (changingRef.current > 0) return
      if (reading) {
        again = true
        return
      }
      reading = true
      const seq = changeSeqRef.current
      api
        .getToolbox()
        .then(
          (t) => {
            if (active && seq === changeSeqRef.current) show(t)
          },
          () => undefined,
        )
        .finally(() => {
          reading = false
          if (again && active) {
            again = false
            refresh()
          }
        })
    }
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') refresh()
    }

    // 신호 흐름은 첫 읽기가 끝난 뒤에 연다. 처음 온 브라우저는 guest cookie 가 없어서, 둘을 함께 보내면
    // 요청마다 다른 guest 가 발급되고 흐름이 이 화면과 다른 주인에 붙는다.
    load().finally(() => {
      if (active) unsubscribe = subscribeToolboxChanges(refresh, refresh)
    })
    document.addEventListener('visibilitychange', refreshWhenVisible)
    window.addEventListener('focus', refresh)
    return () => {
      active = false
      unsubscribe?.()
      document.removeEventListener('visibilitychange', refreshWhenVisible)
      window.removeEventListener('focus', refresh)
    }
  }, [load, show])

  // 로그인 · 로그아웃 · 「다시 시도」 뒤 다시 읽기. 그 전에 떠난 다시 읽기의 응답(옛 상태)은 버린다.
  const reload = useCallback(() => {
    changeSeqRef.current += 1
    return load()
  }, [load])

  const change = useCallback(async (mcpId: string, call: (id: string) => Promise<Toolbox>) => {
    changingRef.current += 1
    changeSeqRef.current += 1
    setPending((p) => new Set(p).add(mcpId))
    setErrors((prev) => {
      const next = { ...prev }
      delete next[mcpId]
      return next
    })
    try {
      show(await call(mcpId))
    } catch (e) {
      setErrors((prev) => ({ ...prev, [mcpId]: (e as Error).message }))
    } finally {
      changingRef.current -= 1
      changeSeqRef.current += 1
      setPending((p) => {
        const next = new Set(p)
        next.delete(mcpId)
        return next
      })
    }
  }, [show])

  const value = useMemo<ToolboxState>(
    () => ({
      registered: toolbox ? new Set(toolbox.mcp_ids) : null,
      mcps: toolbox?.mcps ?? [],
      loadError,
      pending,
      errors,
      add: (id) => change(id, api.addToToolbox),
      remove: (id) => change(id, api.removeFromToolbox),
      reload,
    }),
    [toolbox, loadError, pending, errors, change, reload],
  )

  return <ToolboxContext.Provider value={value}>{children}</ToolboxContext.Provider>
}
