import type { McpCard } from '../types/api'

type Badge = 'online' | 'offline' | 'unknown' | 'development'

const LABEL: Record<Badge, string> = {
  online: '사용 가능',
  offline: '사용 불가',
  unknown: '상태 모름',
  development: '개발 중',
}

// 개발 중 MCP 는 runtime 상태가 아니라 단계로 보인다 (사용 불가 · 상태 모름이 아니다).
function badgeOf(mcp: Pick<McpCard, 'lifecycle' | 'status'>): Badge {
  return mcp.lifecycle === 'development' ? 'development' : (mcp.status ?? 'unknown')
}

// 점 + 글자. 색만으로 상태를 말하지 않는다.
export default function StatusBadge({ mcp }: { mcp: Pick<McpCard, 'lifecycle' | 'status'> }) {
  const badge = badgeOf(mcp)
  return (
    <span className={`status status-${badge}`}>
      <span className="status-dot" aria-hidden="true" />
      {LABEL[badge]}
    </span>
  )
}
