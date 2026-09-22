import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import AiPanel from '../components/AiPanel'
import McpIcon from '../components/McpIcon'
import MockNotice from '../components/MockNotice'
import StatusBadge from '../components/StatusBadge'
import ToolboxButton from '../components/ToolboxButton'
import ToolList from '../components/ToolList'
import { useDemoRun } from '../demo/useDemoRun'
import type { McpDetail } from '../types/api'

// serverId 가 바뀌면 key 로 새로 그려 이전 MCP 의 상태를 남기지 않는다.
export default function McpDetailPage() {
  const { serverId = '' } = useParams()
  return <McpDetailView key={serverId} serverId={serverId} />
}

type Tab = 'tools' | 'info'

function McpDetailView({ serverId }: { serverId: string }) {
  const [mcp, setMcp] = useState<McpDetail | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [tab, setTab] = useState<Tab>('tools')
  const demo = useDemoRun(serverId)

  useEffect(() => {
    api.getMcp(serverId).then(setMcp, (e: ApiError) => setError(e))
  }, [serverId])

  if (error) {
    return (
      <div className="state-block" role="alert">
        <p>{error.status === 404 ? 'MCP 를 찾을 수 없습니다.' : error.message}</p>
        <Link to="/" className="pill pill-outline">MCP 탐색으로</Link>
      </div>
    )
  }
  if (!mcp) return <div className="state-block muted">MCP 정보를 불러오는 중…</div>

  return (
    <>
      <nav className="breadcrumb" aria-label="위치">
        <Link to="/">MCP 탐색</Link>
        <span aria-hidden="true">›</span>
        <span aria-current="page">{mcp.display_name}</span>
      </nav>

      <div className="detail-layout">
        <div className="detail-main">
          <section className="detail-identity">
            <McpIcon serverId={mcp.server_id} size="lg" />
            <div>
              <h1>{mcp.display_name}</h1>
              <ToolboxButton serverId={mcp.server_id} variant="detail" />
            </div>
          </section>

          <dl className="stats">
            <div>
              <dt>MCP 상태</dt>
              <dd><StatusBadge status={mcp.status} /></dd>
            </div>
            <div>
              <dt>제공</dt>
              <dd>{mcp.organization || '—'}</dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>{mcp.tools.length}</dd>
            </div>
            <div>
              <dt>분류</dt>
              <dd>{mcp.category || '—'}</dd>
            </div>
          </dl>

          <p className="detail-summary">{mcp.summary || '설명이 아직 없습니다.'}</p>
          <MockNotice source={mcp.source} />

          <div className="tabs" role="tablist" aria-label="MCP 상세">
            <button type="button" role="tab" id="tab-tools" aria-controls="panel-tools" aria-selected={tab === 'tools'} onClick={() => setTab('tools')}>
              Tool 목록 {mcp.tools.length}
            </button>
            <button type="button" role="tab" id="tab-info" aria-controls="panel-info" aria-selected={tab === 'info'} onClick={() => setTab('info')}>
              MCP 정보
            </button>
          </div>

          {tab === 'tools' && (
            <div role="tabpanel" id="panel-tools" aria-labelledby="tab-tools">
              <ToolList tools={mcp.tools} />
            </div>
          )}
          {tab === 'info' && (
            <div role="tabpanel" id="panel-info" aria-labelledby="tab-info" className="info-box">
              <dl>
                <dt>Tools</dt>
                <dd className="mono-list">{mcp.tools.length > 0 ? mcp.tools.map((t) => t.name).join(', ') : '—'}</dd>
                <dt>서버 ID</dt>
                <dd><code>{mcp.server_id}</code>{mcp.technical_name !== mcp.server_id && <span className="muted"> · {mcp.technical_name}</span>}</dd>
                <dt>대화 예시</dt>
                <dd>
                  {demo.questions && demo.questions.length > 0 ? (
                    <ol className="examples">
                      {demo.questions.map((q) => (
                        <li key={q.question_id}>
                          <button type="button" className="link-button" onClick={() => demo.run(q)} disabled={demo.running}>
                            {q.display_text}
                          </button>
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <span className="muted">{demo.questions ? '준비된 대화 예시가 없습니다.' : '불러오는 중…'}</span>
                  )}
                </dd>
              </dl>
            </div>
          )}
        </div>

        <div className="detail-side">
          <AiPanel demo={demo} mcpName={mcp.display_name} />
        </div>
      </div>
    </>
  )
}
