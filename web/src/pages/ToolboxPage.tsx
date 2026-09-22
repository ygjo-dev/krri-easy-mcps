import { Link } from 'react-router-dom'
import McpCard from '../components/McpCard'
import { useToolbox } from '../toolbox/context'

export default function ToolboxPage() {
  const { registered, mcps, loadError, reload } = useToolbox()

  return (
    <>
      <section className="page-head">
        <h1>도구함</h1>
        <p>AI 에서 사용할 MCP 를 모아 둔 곳입니다. MCP 탐색에서 추가하고, 여기서 해제할 수 있습니다.</p>
      </section>

      {loadError && (
        <div className="state-block" role="alert">
          <p>{loadError}</p>
          <button type="button" className="pill pill-outline" onClick={reload}>다시 시도</button>
        </div>
      )}
      {registered === null && !loadError && <div className="state-block muted">도구함을 불러오는 중…</div>}
      {registered !== null && mcps.length === 0 && (
        <div className="state-block">
          <p>아직 도구함에 등록한 MCP 가 없습니다.</p>
          <p className="muted">MCP 탐색에서 사용할 MCP 를 추가하세요.</p>
          <Link to="/" className="pill pill-primary">MCP 탐색</Link>
        </div>
      )}
      {mcps.length > 0 && (
        <>
          <p className="toolbar-count">등록한 MCP <strong>{mcps.length}</strong></p>
          <ul className="card-grid">
            {mcps.map((m) => (
              <li key={m.server_id}>
                <McpCard mcp={m} action="remove" />
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  )
}
