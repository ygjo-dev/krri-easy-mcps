import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import type { AuthUser } from '../types/api'
import { useToolbox } from '../toolbox/context'
import { AuthContext, type AuthContextValue } from './context'

// 로그인 · 로그아웃이 끝나면 도구함을 서버에서 다시 읽는다. 로그인 때 BFF 가 계정 도구함과 이 브라우저의
// Gateway guest selection 을 맞추므로(첫 로그인 = 가져오기, 저장된 계정 = 복원) 그 결과가 바로 화면에 온다.
export default function AuthProvider({ children }: { children: ReactNode }) {
  const { reload } = useToolbox()
  const [user, setUser] = useState<AuthUser | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let active = true
    api
      .me()
      .then(
        (state) => {
          if (active) setUser(state.user)
        },
        () => undefined,
      )
      .finally(() => {
        if (active) setReady(true)
      })
    return () => {
      active = false
    }
  }, [])

  const login = useCallback(
    async (username: string, password: string) => {
      const state = await api.login(username, password)
      setUser(state.user)
      await reload()
    },
    [reload],
  )

  const logout = useCallback(async () => {
    await api.logout()
    setUser(null)
    await reload()
  }, [reload])

  const value = useMemo<AuthContextValue>(
    () => ({ user, ready, isAdmin: user?.role === 'ADMIN', login, logout }),
    [user, ready, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
