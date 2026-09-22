import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import MockNotice from '../components/MockNotice'
import StatusBadge from '../components/StatusBadge'
import ToolboxButton from '../components/ToolboxButton'
import type { McpCard } from '../types/api'

export default function CatalogPage() {
  const [cards, setCards] = useState<McpCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')

  useEffect(() => {
    api.listMcps().then(setCards, (e: Error) => setError(e.message))
  }, [])

  const categories = useMemo(() => [...new Set((cards ?? []).map((c) => c.category).filter(Boolean))], [cards])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (cards ?? []).filter(
      (c) =>
        (!category || c.category === category) &&
        (!q ||
          [c.display_name, c.summary, c.category, c.organization, c.server_id].some((v) => v.toLowerCase().includes(q))),
    )
  }, [cards, query, category])

  if (error) return <p className="error">{error}</p>
  if (!cards) return <p className="muted">불러오는 중…</p>

  return (
    <section>
      <h1>MCP 탐색</h1>
      <MockNotice source={cards[0]?.source ?? ''} />
      <div className="filters">
        <input
          type="search"
          placeholder="이름, 설명, 기관으로 검색"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="MCP 검색"
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="카테고리">
          <option value="">전체 카테고리</option>
          {categories.map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
      </div>
      {visible.length === 0 ? (
        <p className="muted">조건에 맞는 MCP 가 없습니다.</p>
      ) : (
        <ul className="cards">
          {visible.map((c) => (
            <li key={c.server_id} className="card">
              {/* 버튼은 Link 밖에 둔다. 누를 때 상세로 넘어가지 않게. */}
              <Link to={`/mcps/${c.server_id}`} className="card-link">
                <div className="card-head">
                  <strong>{c.display_name}</strong>
                  <StatusBadge status={c.status} />
                </div>
                <p>{c.summary}</p>
                <div className="meta">
                  <span>{c.category}</span>
                  <span>{c.organization}</span>
                  <span>Tool {c.tool_count}개</span>
                </div>
              </Link>
              <div className="card-actions">
                <ToolboxButton serverId={c.server_id} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
