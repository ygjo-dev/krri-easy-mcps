import type { Status } from '../types/api'

const STATUS_LABEL: Record<Status, string> = { online: '사용 가능', offline: '사용 불가', unknown: '상태 모름' }

// 점 + 글자. 색만으로 상태를 말하지 않는다.
export default function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`status status-${status}`}>
      <span className="status-dot" aria-hidden="true" />
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}
