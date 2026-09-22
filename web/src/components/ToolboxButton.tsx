import { useToolbox } from '../toolbox/context'

// card     Catalog 카드. 등록 전 「+ 도구함에 등록」, 뒤 「✓ 등록됨」 (해제는 상세 · 도구함에서)
// detail   상세 주 CTA. 등록 ↔ 해제
// remove   도구함 카드. 「해제」
type Variant = 'card' | 'detail' | 'remove'

export default function ToolboxButton({ serverId, variant }: { serverId: string; variant: Variant }) {
  const { registered, pending, errors, add, remove } = useToolbox()
  const busy = pending.has(serverId)
  const error = errors[serverId]

  if (registered === null) return null
  const isRegistered = registered.has(serverId)

  let control
  if (isRegistered && variant === 'card') {
    control = <span className="pill pill-applied">✓ 등록됨</span>
  } else if (isRegistered) {
    control = (
      <button type="button" className="pill pill-outline" onClick={() => remove(serverId)} disabled={busy} aria-busy={busy}>
        {busy ? '해제 중…' : variant === 'detail' ? '✓ 도구함에서 해제' : '해제'}
      </button>
    )
  } else {
    control = (
      <button
        type="button"
        className={`pill ${variant === 'detail' ? 'pill-primary' : 'pill-ghost'}`}
        onClick={() => add(serverId)}
        disabled={busy}
        aria-busy={busy}
      >
        {busy ? '등록 중…' : '+ 도구함에 등록'}
      </button>
    )
  }

  return (
    <span className="toolbox-action">
      {control}
      {error && <span className="action-error" role="alert">{error}</span>}
    </span>
  )
}
