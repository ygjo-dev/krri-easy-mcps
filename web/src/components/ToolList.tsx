import type { Tool, ToolParameter } from '../types/api'
import { ChevronIcon } from './Icons'

// PlayMCP 의 Tool 카드(이름 · 용도 · 파라미터)를 접히는 행으로 둔다. 40개도 한 화면에서 훑을 수 있게.
// Tool 이 몇 개 안 되면 처음부터 펼친다.
const OPEN_BY_DEFAULT_MAX = 3

function signature(p: ToolParameter): string {
  if (p.enum && p.enum.length > 0) return `${p.name}: ${p.enum.map((v) => JSON.stringify(v)).join(' | ')}`
  return `${p.name}: ${p.type}`
}

// 긴 이름(adminBoundary.findBoundaryByPoint)은 점 뒤에서 먼저 줄을 바꾼다.
function breakableName(name: string) {
  const parts = name.split('.')
  return parts.map((part, i) => (
    <span key={i}>
      {part}
      {i < parts.length - 1 && <>.<wbr /></>}
    </span>
  ))
}

function hasDefault(p: ToolParameter): boolean {
  return p.default !== null && p.default !== undefined
}

export default function ToolList({ tools }: { tools: Tool[] }) {
  if (tools.length === 0) {
    return <p className="empty-inline">Gateway 가 이 MCP 의 Tool 목록을 받지 못했습니다.</p>
  }
  const openAll = tools.length <= OPEN_BY_DEFAULT_MAX
  return (
    <ul className="tool-list">
      {tools.map((t) => (
        <li key={t.name}>
          <details className="tool" open={openAll}>
            <summary>
              <span className="tool-name">{breakableName(t.name)}</span>
              <span className="tool-short">{t.description.split('\n')[0]}</span>
              <span className="tool-count">{t.parameters.length > 0 ? `파라미터 ${t.parameters.length}` : '파라미터 없음'}</span>
              <ChevronIcon />
            </summary>
            <dl className="tool-body">
              <dt>용도</dt>
              <dd className="tool-desc">{t.description || '설명이 없습니다.'}</dd>
              <dt>파라미터</dt>
              <dd>
                {t.parameters.length === 0 ? (
                  <span className="muted">없음</span>
                ) : (
                  <>
                    <ul className="param-chips">
                      {t.parameters.map((p) => (
                        <li key={p.name}>
                          <code className="param-chip">
                            {signature(p)}
                            {p.required && <span className="param-required" title="필수">필수</span>}
                          </code>
                        </li>
                      ))}
                    </ul>
                    {t.parameters.some((p) => p.description || hasDefault(p)) && (
                      <ul className="param-notes">
                        {t.parameters
                          .filter((p) => p.description || hasDefault(p))
                          .map((p) => (
                            <li key={p.name}>
                              <code>{p.name}</code> {p.description}
                              {hasDefault(p) && <span className="muted"> (기본값 {JSON.stringify(p.default)})</span>}
                            </li>
                          ))}
                      </ul>
                    )}
                  </>
                )}
              </dd>
            </dl>
          </details>
        </li>
      ))}
    </ul>
  )
}
