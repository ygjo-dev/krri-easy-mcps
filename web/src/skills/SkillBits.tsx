import type { SkillCompat } from '../types/api'

const PALETTE = ['#2f6fed', '#0f9d76', '#c2410c', '#7c3aed', '#be185d', '#0e7490', '#a16207']

// 제목 첫 글자 모노그램. 색은 id 로 정한다 (같은 Skill 은 늘 같은 색).
export function SkillIcon({ id, title, size = 'md' }: { id: string; title: string; size?: 'md' | 'lg' }) {
  let hash = 0
  for (const ch of id) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0
  const letter = [...(title.trim() || id)][0]?.toUpperCase() ?? 'S'
  return (
    <span className={`mcp-icon mcp-icon-${size} skill-icon`} style={{ background: PALETTE[hash % PALETTE.length] }} aria-hidden="true">
      {letter}
    </span>
  )
}

// 각 서비스 Skills 에 그대로 올릴 수 있는지. 설치 여부가 아니다.
export function CompatBadges({ compat }: { compat: SkillCompat }) {
  return (
    <span className="compat-badges">
      <span className={`compat-badge${compat.chatgpt ? '' : ' compat-off'}`} title={compat.chatgpt ? 'ChatGPT Skills 에 올릴 수 있는 형식' : '확인 필요'}>
        ChatGPT
      </span>
      <span className={`compat-badge${compat.claude ? '' : ' compat-off'}`} title={compat.claude ? 'Claude Skills 에 올릴 수 있는 형식' : '확인 필요'}>
        Claude
      </span>
    </span>
  )
}

export function TagList({ tags }: { tags: string[] }) {
  if (tags.length === 0) return null
  return (
    <ul className="tag-list skill-tags">
      {tags.map((t) => (
        <li key={t} className="chip">{t}</li>
      ))}
    </ul>
  )
}
