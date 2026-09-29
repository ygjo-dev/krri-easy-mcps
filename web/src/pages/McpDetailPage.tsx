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

// mcpId 가 바뀌면 key 로 새로 그려 이전 MCP 의 상태를 남기지 않는다.
export default function McpDetailPage() {
  const { mcpId = '' } = useParams()
  return <McpDetailView key={mcpId} mcpId={mcpId} />
}

type Tab = 'tools' | 'info'

function McpDetailView({ mcpId }: { mcpId: string }) {
  const [mcp, setMcp] = useState<McpDetail | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [tab, setTab] = useState<Tab>('tools')
  const demo = useDemoRun(mcpId)

  useEffect(() => {
    api.getMcp(mcpId).then(setMcp, (e: ApiError) => setError(e))
  }, [mcpId])

  if (error) {
    return (
      <div className="state-block" role="alert">
        <p>{error.status === 404 ? 'MCP 를 찾을 수 없습니다.' : error.message}</p>
        <Link to="/" className="pill pill-outline">MCP 탐색으로</Link>
      </div>
    )
  }
  if (!mcp) return <div className="state-block muted">MCP 정보를 불러오는 중…</div>
  const developing = mcp.lifecycle === 'development'

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
            <McpIcon mcpId={mcp.mcp_id} size="lg" />
            <div>
              <h1>{mcp.display_name}</h1>
              {developing ? (
                <p className="stage-note">개발 중인 MCP 입니다. 공개되면 도구함에 등록할 수 있습니다.</p>
              ) : (
                <ToolboxButton mcpId={mcp.mcp_id} variant="detail" />
              )}
            </div>
          </section>

          <dl className="stats">
            <div>
              <dt>MCP 상태</dt>
              <dd><StatusBadge mcp={mcp} /></dd>
            </div>
            <div>
              <dt>제공</dt>
              <dd>{mcp.organization || '—'}</dd>
            </div>
            <div>
              <dt>Tools</dt>
              <dd>{developing ? '—' : mcp.tools.length}</dd>
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
              Tool 목록{!developing && ` ${mcp.tools.length}`}
            </button>
            <button type="button" role="tab" id="tab-info" aria-controls="panel-info" aria-selected={tab === 'info'} onClick={() => setTab('info')}>
              MCP 정보
            </button>
          </div>

          {tab === 'tools' && (
            <div role="tabpanel" id="panel-tools" aria-labelledby="tab-tools">
              {developing ? (
                <p className="empty-inline">개발 중인 MCP 입니다. Tool 목록은 공개된 뒤에 볼 수 있습니다.</p>
              ) : (
                <ToolList tools={mcp.tools} />
              )}
            </div>
          )}
          {tab === 'info' && (
            <div role="tabpanel" id="panel-info" aria-labelledby="tab-info" className="info-box">
              <dl>
                <dt>Tools</dt>
                <dd className="mono-list">{mcp.tools.length > 0 ? mcp.tools.map((t) => t.name).join(', ') : '—'}</dd>
                <dt>MCP ID</dt>
                <dd><code>{mcp.mcp_id}</code></dd>
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
          {developing ? (
            <aside className="ai-panel" aria-label="AI로 사용해보기">
              <header className="ai-head">
                <strong>AI로 사용해보기</strong>
              </header>
              <div className="ai-body">
                <div className="ai-intro">
                  <p>개발 중인 MCP 는 아직 AI 로 실행할 수 없습니다.</p>
                </div>
              </div>
            </aside>
          ) : (
            <AiPanel demo={demo} />
          )}
        </div>
      </div>
    </>
  )
}
