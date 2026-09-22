import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import MockNotice from '../components/MockNotice'
import StatusBadge from '../components/StatusBadge'
import ToolList from '../components/ToolList'
import TryWithAi from '../components/TryWithAi'
import type { McpDetail } from '../types/api'

// serverId 가 바뀌면 key 로 새로 그려 이전 MCP 의 상태를 남기지 않는다.
export default function McpDetailPage() {
  const { serverId = '' } = useParams()
  return <McpDetailView key={serverId} serverId={serverId} />
}

function McpDetailView({ serverId }: { serverId: string }) {
  const [mcp, setMcp] = useState<McpDetail | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.getMcp(serverId).then(setMcp, (e: Error) => setError(e.message))
  }, [serverId])

  if (error) return <p className="error">{error}</p>
  if (!mcp) return <p className="muted">불러오는 중…</p>

  return (
    <section>
      <p><Link to="/">← MCP 탐색</Link></p>
      <div className="detail-head">
        <h1>{mcp.display_name}</h1>
        <StatusBadge status={mcp.status} />
      </div>
      <p>{mcp.summary}</p>
      <div className="meta">
        <span>{mcp.category}</span>
        <span>{mcp.organization}</span>
        <code>{mcp.server_id}</code>
        {mcp.technical_name !== mcp.server_id && <span>기술 이름 {mcp.technical_name}</span>}
      </div>
      <MockNotice source={mcp.source} />

      <h2>AI로 사용해보기</h2>
      <TryWithAi serverId={mcp.server_id} />

      <h2>Tool 목록 <span className="muted">({mcp.tools.length})</span></h2>
      <ToolList tools={mcp.tools} />
    </section>
  )
}
