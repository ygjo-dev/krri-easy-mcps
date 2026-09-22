import { Link } from 'react-router-dom'
import type { McpCard as McpCardData } from '../types/api'
import { WrenchIcon } from './Icons'
import McpIcon from './McpIcon'
import StatusBadge from './StatusBadge'
import ToolboxButton from './ToolboxButton'

// 카드 전체가 상세로 가는 링크처럼 동작한다 (제목 Link 를 카드 크기로 늘림).
// 도구함 버튼은 Link 밖의 형제라서 누를 때 상세로 넘어가지 않고, 중첩된 interactive 요소도 없다.
export default function McpCard({ mcp, action }: { mcp: McpCardData; action: 'card' | 'remove' }) {
  return (
    <article className="mcp-card">
      <div className="mcp-card-head">
        <div className="mcp-card-title">
          <h3>
            <Link to={`/mcps/${mcp.server_id}`} className="mcp-card-link">{mcp.display_name}</Link>
          </h3>
          {mcp.organization && <p className="publisher">{mcp.organization}</p>}
        </div>
        <McpIcon serverId={mcp.server_id} />
      </div>
      <p className="mcp-card-summary">{mcp.summary || '설명이 아직 없습니다.'}</p>
      <div className="mcp-card-foot">
        <div className="card-meta">
          <span><WrenchIcon /> Tools {mcp.tool_count}</span>
          <StatusBadge status={mcp.status} />
          {mcp.category && <span>{mcp.category}</span>}
        </div>
        <div className="mcp-card-action">
          <ToolboxButton serverId={mcp.server_id} variant={action} />
        </div>
      </div>
    </article>
  )
}
