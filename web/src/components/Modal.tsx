import { useEffect, useRef, type ReactNode } from 'react'

// 브라우저 기본 <dialog> 로 띄우는 창. 닫기는 부모가 이 component 를 내려서 한다 (dialog.close() 를 부르지 않는다).
// Esc 는 onClose (busy 동안은 무시).
export default function Modal({
  title,
  onClose,
  busy = false,
  wide = false,
  children,
}: {
  title: string
  onClose: () => void
  busy?: boolean
  wide?: boolean
  children: ReactNode
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    if (dialog && !dialog.open) dialog.showModal()
  }, [])

  return (
    <dialog
      ref={dialogRef}
      className={`modal${wide ? ' modal-wide' : ''}`}
      aria-label={title}
      onCancel={(e) => {
        e.preventDefault()
        if (!busy) onClose()
      }}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button type="button" className="modal-close" onClick={onClose} disabled={busy} aria-label="닫기">×</button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  )
}
