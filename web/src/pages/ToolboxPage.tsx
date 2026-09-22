import { Link } from 'react-router-dom'
import StatusBadge from '../components/StatusBadge'
import ToolboxButton from '../components/ToolboxButton'
import { useToolbox } from '../toolbox/context'

export default function ToolboxPage() {
  const { registered, mcps, loadError } = useToolbox()

  return (
    <section>
      <h1>도구함</h1>
      <p className="muted">KRRI 에 있는 MCP 중 내가 쓰려고 담아 둔 것입니다.</p>
      {loadError && <p className="error">{loadError}</p>}
      {registered === null && !loadError && <p className="muted">불러오는 중…</p>}
      {registered !== null && mcps.length === 0 && (
        <div className="empty">
          <p>아직 도구함에 등록한 MCP 가 없습니다.</p>
          <p className="muted">MCP 탐색에서 사용할 MCP 를 추가하세요.</p>
          <Link to="/" className="button">MCP 탐색</Link>
        </div>
      )}
      {mcps.length > 0 && (
        <ul className="toolbox-list">
          {mcps.map((m) => (
            <li key={m.server_id} className="card">
              <div className="card-head">
                <Link to={`/mcps/${m.server_id}`}><strong>{m.display_name}</strong></Link>
                <ToolboxButton serverId={m.server_id} allowRemove />
              </div>
              <p>{m.summary}</p>
              <div className="meta">
                <span>{m.category}</span>
                <StatusBadge status={m.status} />
                <span>Tool {m.tool_count}개</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
