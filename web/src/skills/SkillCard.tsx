import { Link } from 'react-router-dom'
import type { SkillCard as SkillCardData } from '../types/api'
import { formatDate } from './format'
import { CompatBadges, SkillIcon, TagList } from './SkillBits'

// MCP 카드와 같은 틀. 카드 전체가 상세 링크다.
export default function SkillCard({ skill }: { skill: SkillCardData }) {
  return (
    <article className="mcp-card skill-card">
      <div className="mcp-card-head">
        <div className="mcp-card-title">
          <h3>
            <Link to={`/skills/${encodeURIComponent(skill.id)}`} className="mcp-card-link">{skill.title}</Link>
          </h3>
          <p className="publisher">v{skill.version}{skill.author && ` · ${skill.author}`}</p>
        </div>
        <SkillIcon id={skill.id} title={skill.title} />
      </div>
      <p className="mcp-card-summary">{skill.description}</p>
      <TagList tags={skill.tags} />
      <div className="mcp-card-foot">
        <CompatBadges compat={skill.compat} />
        <span className="skill-updated">{formatDate(skill.updated_at)} 업데이트</span>
      </div>
    </article>
  )
}
