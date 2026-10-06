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
import type { ConnectedDataset, McpDetail } from '../types/api'

// geometryKind 중 사용자에게 뜻이 있는 것만. auto · 모르는 값은 표시하지 않는다.
const GEOMETRY_LABEL: Record<string, string> = { point: '점', line: '선', polygon: '면', mixed: '혼합' }

// Gateway updatedAt 은 group server 의 마지막 상태 확인 시각이다.
function formatCheckedAt(value: string | null): string | null {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(date)
}

function DatasetList({ datasets }: { datasets: ConnectedDataset[] }) {
  return (
    <ul className="dataset-list">
      {datasets.map((d, i) => (
        <li key={`${d.name}-${i}`}>
          <div className="dataset-head">
            <strong>{d.name}</strong>
            {d.geometry_kind && GEOMETRY_LABEL[d.geometry_kind] && (
              <span className="chip">{GEOMETRY_LABEL[d.geometry_kind]}</span>
            )}
          </div>
          {d.description && <p>{d.description}</p>}
        </li>
      ))}
    </ul>
  )
}

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
        <Link to="/" className="pill pill-outline">전체 MCP으로</Link>
      </div>
    )
  }
  if (!mcp) return <div className="state-block muted">MCP 정보를 불러오는 중…</div>
  const developing = mcp.lifecycle === 'development'
  // 개요는 요약과 다를 때만 (같은 글을 두 번 보이지 않게). 없으면 요약이 곧 개요다.
  const overview = mcp.long_description && mcp.long_description !== mcp.summary ? mcp.long_description : ''
  const checkedAt = formatCheckedAt(mcp.updated_at)

  return (
    <>
      <nav className="breadcrumb" aria-label="위치">
        <Link to="/">전체 MCP</Link>
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
                <p className="stage-note">개발 중인 MCP 입니다. 공개되면 내 MCP에 등록할 수 있습니다.</p>
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
          {mcp.tags.length > 0 && (
            <ul className="tag-list" aria-label="태그">
              {mcp.tags.map((t) => (
                <li key={t} className="chip">{t}</li>
              ))}
            </ul>
          )}
          <MockNotice source={mcp.source} />

          {overview && (
            <section className="detail-section" aria-labelledby="sec-overview">
              <h2 id="sec-overview">개요</h2>
              <p className="overview-text">{overview}</p>
            </section>
          )}

          {mcp.connected_datasets.length > 0 && (
            <section className="detail-section" aria-labelledby="sec-datasets">
              <h2 id="sec-datasets">
                연결 데이터 <span className="muted">{mcp.connected_datasets.length}</span>
              </h2>
              <p className="section-note">이 MCP 가 KRRI-ASAP Data Library 에 제공하는 데이터입니다.</p>
              <DatasetList datasets={mcp.connected_datasets} />
            </section>
          )}

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
                <dt>MCP ID</dt>
                <dd><code>{mcp.mcp_id}</code></dd>
                <dt>제공</dt>
                <dd>{mcp.organization || '—'}</dd>
                <dt>상태</dt>
                <dd><StatusBadge mcp={mcp} /></dd>
                <dt>분류</dt>
                <dd>{mcp.category || '—'}</dd>
                {!developing && (
                  <>
                    <dt>Tool 수</dt>
                    <dd>{mcp.tools.length}개</dd>
                    <dt>Tools</dt>
                    <dd className="mono-list">{mcp.tools.length > 0 ? mcp.tools.map((t) => t.name).join(', ') : '—'}</dd>
                  </>
                )}
                {checkedAt && (
                  <>
                    <dt>상태 확인</dt>
                    <dd>{checkedAt}</dd>
                  </>
                )}
                <dt>AI에게 이렇게 물어보세요</dt>
                <dd>
                  {demo.questions && demo.questions.length > 0 ? (
                    <ol className="examples">
                      {demo.questions.map((q) => (
                        <li key={q.question_id}>
                          {q.runnable ? (
                            <button type="button" className="link-button" onClick={() => demo.run(q)} disabled={demo.running}>
                              {q.display_text}
                            </button>
                          ) : (
                            <span>{q.display_text} <span className="muted">(예시 · EASY 실행 전)</span></span>
                          )}
                        </li>
                      ))}
                    </ol>
                  ) : (
                    <span className="muted">{demo.questions ? '준비된 질문이 없습니다.' : '불러오는 중…'}</span>
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
