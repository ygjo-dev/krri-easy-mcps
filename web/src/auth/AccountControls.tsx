import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useAuth } from './context'

// 헤더 오른쪽. 비로그인: [로그인]. 로그인: 이름 · (관리자) · [로그아웃].
export default function AccountControls() {
  const { user, ready, isAdmin, logout } = useAuth()
  const [dialogOpen, setDialogOpen] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!ready) return <div className="account" />

  if (!user) {
    return (
      <div className="account">
        <button type="button" className="pill pill-outline pill-sm" onClick={() => setDialogOpen(true)}>
          로그인
        </button>
        {dialogOpen && <LoginDialog onClose={() => setDialogOpen(false)} />}
      </div>
    )
  }

  const onLogout = () => {
    setBusy(true)
    logout()
      .catch(() => undefined)
      .finally(() => setBusy(false))
  }

  return (
    <div className="account">
      <span className="account-name" title={user.username}>{user.username}</span>
      {isAdmin && <span className="role-badge">관리자</span>}
      <button type="button" className="pill pill-ghost" onClick={onLogout} disabled={busy} aria-busy={busy}>
        로그아웃
      </button>
    </div>
  )
}

function LoginDialog({ onClose }: { onClose: () => void }) {
  const { login } = useAuth()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // 닫기는 부모가 이 component 를 내려서 한다 (dialog.close() 를 부르지 않는다).
  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      onClose()
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={dialogRef}
      className="login-dialog"
      aria-labelledby="login-title"
      onCancel={(e) => {
        e.preventDefault()
        if (!busy) onClose()
      }}
    >
      <form className="login-form" onSubmit={onSubmit}>
        <h2 id="login-title">로그인</h2>
        <p className="login-note">KRRI EASY MCPs 계정입니다. 로그인하면 도구함이 계정에 저장됩니다.</p>
        <label className="field">
          아이디
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            autoCapitalize="none"
            spellCheck={false}
            autoFocus
            required
          />
        </label>
        <label className="field">
          비밀번호
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error && <p className="login-error" role="alert">{error}</p>}
        <div className="login-actions">
          <button type="button" className="pill pill-outline" onClick={onClose} disabled={busy}>취소</button>
          <button type="submit" className="pill pill-primary" disabled={busy} aria-busy={busy}>
            {busy ? '로그인 중…' : '로그인'}
          </button>
        </div>
      </form>
    </dialog>
  )
}
