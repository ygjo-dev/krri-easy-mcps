import { useToolbox } from '../toolbox/context'

// card     Catalog 카드. 등록 전 「+ 내 MCP에 등록」, 뒤 「✓ 등록됨」 (해제는 상세 · 내 MCP에서)
// detail   상세 주 CTA. 등록 ↔ 해제
// remove   내 MCP 카드. 「해제」
type Variant = 'card' | 'detail' | 'remove'

export default function ToolboxButton({ mcpId, variant }: { mcpId: string; variant: Variant }) {
  const { registered, pending, errors, add, remove } = useToolbox()
  const busy = pending.has(mcpId)
  const error = errors[mcpId]

  if (registered === null) return null
  const isRegistered = registered.has(mcpId)

  let control
  if (isRegistered && variant === 'card') {
    control = <span className="pill pill-applied">✓ 등록됨</span>
  } else if (isRegistered) {
    control = (
      <button type="button" className="pill pill-outline" onClick={() => remove(mcpId)} disabled={busy} aria-busy={busy}>
        {busy ? '해제 중…' : variant === 'detail' ? '✓ 내 MCP에서 해제' : '해제'}
      </button>
    )
  } else {
    control = (
      <button
        type="button"
        className={`pill ${variant === 'detail' ? 'pill-primary' : 'pill-ghost'}`}
        onClick={() => add(mcpId)}
        disabled={busy}
        aria-busy={busy}
      >
        {busy ? '등록 중…' : '+ 내 MCP에 등록'}
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
