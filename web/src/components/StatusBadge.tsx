import type { Status } from '../types/api'

const LABEL: Record<Status, string> = { online: '사용 가능', offline: '사용 불가', unknown: '상태 모름' }

export default function StatusBadge({ status }: { status: Status }) {
  return <span className={`badge badge-${status}`}>{LABEL[status] ?? status}</span>
}
