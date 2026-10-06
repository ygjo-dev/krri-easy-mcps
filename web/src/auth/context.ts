import { createContext, useContext } from 'react'
import type { AuthUser } from '../types/api'

// EASY 자체 로그인 상태 (KRRI_ASAP 로그인과 별개).
export interface AuthContextValue {
  // null = 로그인 안 함 (guest). 내 MCP은 로그인과 상관없이 같은 Gateway guest selection 을 쓴다
  user: AuthUser | null
  // 처음 /api/auth/me 를 읽었는지
  ready: boolean
  isAdmin: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthProvider 밖에서 useAuth 를 불렀습니다.')
  return value
}
