import { useEffect, useMemo, useState } from 'react'
import { api } from '../api/client'
import { SearchIcon } from '../components/Icons'
import McpCard from '../components/McpCard'
import MockNotice from '../components/MockNotice'
import type { McpCard as McpCardData } from '../types/api'

export default function CatalogPage() {
  const [cards, setCards] = useState<McpCardData[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('')

  useEffect(() => {
    api.listMcps().then(
      (c) => {
        setCards(c)
        setError(null)
      },
      (e: Error) => setError(e.message),
    )
  }, [attempt])

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

  return (
    <>
      <section className="hero">
        <h1>KRRI MCP 로 만드는<br />새로운 AI 경험</h1>
        <p>AI 가 사용할 수 있는 KRRI 의 MCP 를 찾아보고, 필요한 MCP 를 도구함에 담아 보세요.</p>
      </section>

      <div className="toolbar">
        <p className="toolbar-count">
          {cards ? <>전체 MCP <strong>{visible.length}</strong>{visible.length !== cards.length && ` / ${cards.length}`}</> : ' '}
        </p>
        <div className="toolbar-controls">
          <label className="search">
            <SearchIcon />
            <input
              type="search"
              placeholder="MCP 검색"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="MCP 검색"
            />
          </label>
          <select className="select-plain" value={category} onChange={(e) => setCategory(e.target.value)} aria-label="분류">
            <option value="">전체 분류</option>
            {categories.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="state-block" role="alert">
          <p>{error}</p>
          <button
            type="button"
            className="pill pill-outline"
            onClick={() => {
              setError(null)
              setAttempt((n) => n + 1)
            }}
          >
            다시 시도
          </button>
        </div>
      )}
      {!error && !cards && <div className="state-block muted">MCP 목록을 불러오는 중…</div>}
      {cards && <MockNotice source={cards[0]?.source ?? ''} />}
      {cards && visible.length === 0 && (
        <div className="state-block">
          <p>조건에 맞는 MCP 가 없습니다.</p>
          <button
            type="button"
            className="pill pill-outline"
            onClick={() => {
              setQuery('')
              setCategory('')
            }}
          >
            검색 초기화
          </button>
        </div>
      )}
      {cards && visible.length > 0 && (
        <ul className="card-grid">
          {visible.map((c) => (
            <li key={c.server_id}>
              <McpCard mcp={c} action="card" />
            </li>
          ))}
        </ul>
      )}
    </>
  )
}
