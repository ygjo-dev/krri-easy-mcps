import type { ReactNode } from 'react'

// SKILL.md 미리보기. 제목 · 문단 · 목록 · 인용 · 코드 블록 · 구분선과 inline 코드 · 굵게 · 링크만 그린다.
// HTML 을 끼워 넣지 않고 React 요소로만 만든다 (올린 package 내용이므로). 링크는 http(s) 만 연다.

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)\s]+\))/g
  let last = 0
  let i = 0
  for (const m of text.matchAll(pattern)) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const token = m[0]
    const key = `${keyBase}-${i++}`
    if (token.startsWith('`')) out.push(<code key={key}>{token.slice(1, -1)}</code>)
    else if (token.startsWith('**')) out.push(<strong key={key}>{token.slice(2, -2)}</strong>)
    else {
      const [, label, href] = /^\[([^\]]+)\]\(([^)\s]+)\)$/.exec(token) ?? []
      out.push(
        /^https?:\/\//i.test(href ?? '') ? (
          <a key={key} href={href} target="_blank" rel="noopener noreferrer">{label}</a>
        ) : (
          <span key={key} className="md-ref">{label}</span>
        ),
      )
    }
    last = m.index + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

export default function MarkdownPreview({ text }: { text: string }) {
  const lines = text.split(/\r?\n/)
  const blocks: ReactNode[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const key = `b${i}`
    if (!line.trim()) {
      i++
      continue
    }
    const fence = /^(```|~~~)/.exec(line.trim())
    if (fence) {
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++])
      i++
      blocks.push(<pre key={key} className="md-code"><code>{body.join('\n')}</code></pre>)
      continue
    }
    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      const level = Math.min(heading[1].length + 1, 6)
      const Tag = `h${level}` as 'h2'
      blocks.push(<Tag key={key}>{inline(heading[2], key)}</Tag>)
      i++
      continue
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push(<hr key={key} />)
      i++
      continue
    }
    if (/^\s*>/.test(line)) {
      const body: string[] = []
      while (i < lines.length && /^\s*>/.test(lines[i])) body.push(lines[i++].replace(/^\s*>\s?/, ''))
      blocks.push(<blockquote key={key}>{inline(body.join(' '), key)}</blockquote>)
      continue
    }
    const listItem = /^\s*([-*+]|\d+[.)])\s+/
    if (listItem.test(line)) {
      const ordered = /^\s*\d/.test(line)
      const items: string[] = []
      while (i < lines.length && listItem.test(lines[i])) items.push(lines[i++].replace(listItem, ''))
      const children = items.map((item, n) => <li key={n}>{inline(item, `${key}-${n}`)}</li>)
      blocks.push(ordered ? <ol key={key}>{children}</ol> : <ul key={key}>{children}</ul>)
      continue
    }
    const para: string[] = []
    while (
      i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|~~~|\s*>)/.test(lines[i]) && !listItem.test(lines[i])
    ) para.push(lines[i++].trim())
    if (para.length === 0) para.push(lines[i++].trim()) // 어느 규칙에도 안 맞는 줄도 한 줄은 넘긴다
    blocks.push(<p key={key}>{inline(para.join(' '), key)}</p>)
  }
  return <div className="markdown">{blocks}</div>
}
