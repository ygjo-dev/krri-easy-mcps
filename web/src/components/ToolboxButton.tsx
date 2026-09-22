import { useToolbox } from '../toolbox/context'

// allowRemove=false 면 등록된 뒤 「등록됨」 표시만 한다 (Catalog 카드).
export default function ToolboxButton({ serverId, allowRemove = false }: { serverId: string; allowRemove?: boolean }) {
  const { registered, pending, errors, add, remove } = useToolbox()
  const busy = pending.has(serverId)
  const error = errors[serverId]

  if (registered === null) return null
  const isRegistered = registered.has(serverId)

  let button
  if (isRegistered && !allowRemove) {
    button = <span className="badge badge-online">등록됨</span>
  } else if (isRegistered) {
    button = (
      <button type="button" onClick={() => remove(serverId)} disabled={busy}>
        {busy ? '해제 중…' : '도구함에서 해제'}
      </button>
    )
  } else {
    button = (
      <button type="button" className="primary" onClick={() => add(serverId)} disabled={busy}>
        {busy ? '등록 중…' : '도구함에 등록'}
      </button>
    )
  }

  return (
    <span className="toolbox-action">
      {button}
      {error && <span className="error small" role="alert">{error}</span>}
    </span>
  )
}
