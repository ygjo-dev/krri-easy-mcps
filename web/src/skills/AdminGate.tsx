import type { ReactNode } from 'react'
import { useAuth } from '../auth/context'

// 화면 쪽 안내일 뿐이다. 실제 권한 검사는 BFF (/api/skills 가 401 · 403 을 낸다).
export default function AdminGate({ children }: { children: ReactNode }) {
  const { ready, user, isAdmin } = useAuth()
  if (!ready) return <div className="state-block muted">확인하는 중…</div>
  if (!user) {
    return (
      <div className="state-block gate-block">
        <p>AI Skills 는 관리자 로그인 후 사용할 수 있습니다.</p>
        <p className="muted">오른쪽 위 「로그인」으로 관리자 계정에 로그인하세요.</p>
      </div>
    )
  }
  if (!isAdmin) {
    return (
      <div className="state-block gate-block">
        <p>관리자만 사용할 수 있는 화면입니다.</p>
      </div>
    )
  }
  return <>{children}</>
}
