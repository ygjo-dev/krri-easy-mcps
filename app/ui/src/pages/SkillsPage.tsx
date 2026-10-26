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
  { title: 'Skill ZIP 올리기', text: 'AI 가 내용을 읽고 제목 · 요약 · 태그 · 활용 예시를 자동으로 정리합니다. 원본은 바꾸지 않습니다.' },
  { title: '검토하고 공유', text: '정리 결과를 확인 · 수정해 Library 에 올리면 구성원이 검색해 찾아 씁니다.' },
  { title: 'ChatGPT · Claude 에 직접 추가', text: 'Skill 상세에서 ZIP 을 받아 각 서비스 Skills 화면에 올립니다. 계정 · 요금제에 따라 Skills 기능이 없을 수 있습니다.' },
]

// 검색 대상: 원본 정보 + AI 자동 정리(검토) 정보
function searchText(s: SkillCardData): string {
  return [s.title, s.summary ?? '', s.description, s.author, s.id, s.recommended_for ?? '', ...s.tags, ...s.use_cases,
    ...s.example_prompts].join('\n').toLowerCase()
}

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
        (!q || q.split(/\s+/).every((word) => searchText(s).includes(word))),
    )
  }, [skills, query, tag])

  return (
    <>
      <section className="page-head skills-head">
        <p className="eyebrow">KRRI AI Skills</p>
        <h1>AI Skills</h1>
        <p>
          이미 만든 AI Skill ZIP 을 올리면 AI 가 내용을 이해해 조직 공유용 설명으로 자동 정리합니다.
          구성원은 SKILL.md 를 읽지 않아도 무슨 Skill 인지, 어디에 쓰는지, 어떻게 요청하면 되는지 바로 알 수 있습니다.
        </p>
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
            <input type="search" placeholder="Skill 검색 (예: 회의, 보고서)" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Skill 검색" />
          </label>
          <select className="select-plain" value={tag} onChange={(e) => setTag(e.target.value)} aria-label="태그">
            <option value="">전체 태그</option>
            {tags.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
          <button type="button" className="pill pill-primary" onClick={() => setRegistering(true)}>+ 새 Skill 공유</button>
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
          <p className="muted">이미 만든 Skill ZIP 하나를 올려 보세요. AI 가 공유용 설명을 정리합니다. 예: 회의 내용 정리, 보고서 검토 순서.</p>
          <button type="button" className="pill pill-primary" onClick={() => setRegistering(true)}>+ 새 Skill 공유</button>
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
          onCreated={(created) => navigate(`/skills/${encodeURIComponent(created.id)}`, { state: { shared: true } })}
        />
      )}
    </>
  )
}
