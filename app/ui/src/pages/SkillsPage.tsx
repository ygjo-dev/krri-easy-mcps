import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import { SearchIcon } from '../components/Icons'
import AdminGate from '../skills/AdminGate'
import RegisterSkillDialog from '../skills/RegisterSkillDialog'
import SkillCard from '../skills/SkillCard'
import type { SkillCard as SkillCardData } from '../types/api'

// Skill 이 처음인 사람을 위한 세 단계. 「추가」는 각 서비스에서 사용자가 직접 한다.
const STEPS = [
  { title: 'Skill 등록', text: '반복 업무 방식을 Skill 로 만들어 연구실과 공유합니다.' },
  { title: '필요한 패키지 다운로드', text: 'Skill 상세에서 ChatGPT용 · Claude용 ZIP 을 받습니다.' },
  { title: 'ChatGPT · Claude 에 직접 추가', text: '지원되는 환경의 Skills 화면에 ZIP 을 올립니다. 계정 · 요금제에 따라 Skills 기능이 없을 수 있습니다.' },
]

export default function SkillsPage() {
  return (
    <AdminGate>
      <SkillsLibrary />
    </AdminGate>
  )
}

function SkillsLibrary() {
  const navigate = useNavigate()
  const [skills, setSkills] = useState<SkillCardData[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [query, setQuery] = useState('')
  const [tag, setTag] = useState('')
  const [registering, setRegistering] = useState(false)

  useEffect(() => {
    api.listSkills().then(
      (s) => {
        setSkills(s)
        setError(null)
      },
      (e: Error) => setError(e.message),
    )
  }, [attempt])

  const tags = useMemo(() => [...new Set((skills ?? []).flatMap((s) => s.tags))].sort((a, b) => a.localeCompare(b, 'ko')), [skills])

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return (skills ?? []).filter(
      (s) =>
        (!tag || s.tags.includes(tag)) &&
        (!q || [s.title, s.description, s.author, s.id, ...s.tags].some((v) => v.toLowerCase().includes(q))),
    )
  }, [skills, query, tag])

  return (
    <>
      <section className="page-head skills-head">
        <p className="eyebrow">KRRI AI Skills</p>
        <h1>AI Skills</h1>
        <p>반복되는 업무 방식을 AI 가 그대로 재사용할 수 있도록 Skill 로 만들어 실 구성원과 공유합니다.</p>
      </section>

      <ol className="skill-steps" aria-label="Skill 사용 순서">
        {STEPS.map((step, i) => (
          <li key={step.title}>
            <span className="step-no">{i + 1}</span>
            <div>
              <strong>{step.title}</strong>
              <p>{step.text}</p>
            </div>
          </li>
        ))}
      </ol>

      <div className="toolbar">
        <p className="toolbar-count">
          {skills ? <>전체 Skill <strong>{visible.length}</strong>{visible.length !== skills.length && ` / ${skills.length}`}</> : ' '}
        </p>
        <div className="toolbar-controls">
          <label className="search">
            <SearchIcon />
            <input type="search" placeholder="Skill 검색" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Skill 검색" />
          </label>
          <select className="select-plain" value={tag} onChange={(e) => setTag(e.target.value)} aria-label="태그">
            <option value="">전체 태그</option>
            {tags.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button type="button" className="pill pill-primary" onClick={() => setRegistering(true)}>+ 새 Skill</button>
        </div>
      </div>

      {error && (
        <div className="state-block" role="alert">
          <p>{error}</p>
          <button type="button" className="pill pill-outline" onClick={() => setAttempt((n) => n + 1)}>다시 시도</button>
        </div>
      )}
      {!error && !skills && <div className="state-block muted">Skill 목록을 불러오는 중…</div>}
      {skills && skills.length === 0 && (
        <div className="state-block empty-skills">
          <p>아직 등록된 Skill 이 없습니다.</p>
          <p className="muted">자주 반복하는 업무 하나를 골라 첫 Skill 로 만들어 보세요. 예: 회의 내용 정리, 보고서 검토 순서.</p>
          <button type="button" className="pill pill-primary" onClick={() => setRegistering(true)}>+ 새 Skill 등록</button>
        </div>
      )}
      {skills && skills.length > 0 && visible.length === 0 && (
        <div className="state-block">
          <p>조건에 맞는 Skill 이 없습니다.</p>
          <button
            type="button"
            className="pill pill-outline"
            onClick={() => {
              setQuery('')
              setTag('')
            }}
          >
            검색 초기화
          </button>
        </div>
      )}
      {visible.length > 0 && (
        <ul className="card-grid">
          {visible.map((s) => (
            <li key={s.id}>
              <SkillCard skill={s} />
            </li>
          ))}
        </ul>
      )}

      {registering && (
        <RegisterSkillDialog
          onClose={() => setRegistering(false)}
          onCreated={(created) => navigate(`/skills/${encodeURIComponent(created.id)}`)}
        />
      )}
    </>
  )
}
