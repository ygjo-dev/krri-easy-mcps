import type { InfoDraft } from './infoDraft'

// 서버 제한과 같은 값 (서버가 다시 검사한다)
const LIMITS = { title: 100, summary: 1000, recommendedFor: 300, version: 25, author: 100 }

// 등록 미리보기 · 상세 「공유 정보 수정」 이 같이 쓴다
export default function SkillInfoFields({
  draft,
  onChange,
  disabled,
  versionPlaceholder,
}: {
  draft: InfoDraft
  onChange: (d: InfoDraft) => void
  disabled?: boolean
  versionPlaceholder?: string
}) {
  const set = (key: keyof InfoDraft) => (e: { target: { value: string } }) => onChange({ ...draft, [key]: e.target.value })
  return (
    <fieldset className="info-fields" disabled={disabled}>
      <label className="field">
        제목
        <input value={draft.title} onChange={set('title')} maxLength={LIMITS.title} required />
      </label>
      <label className="field">
        <span className="field-label">요약 <span className="field-optional">비우면 원본 description 을 보입니다</span></span>
        <textarea value={draft.summary} onChange={set('summary')} rows={3} maxLength={LIMITS.summary} />
      </label>
      <label className="field">
        <span className="field-label">태그 <span className="field-optional">쉼표로 구분 · 10개까지</span></span>
        <input value={draft.tags} onChange={set('tags')} placeholder="예: 회의록, 요약" />
      </label>
      <div className="form-row">
        <label className="field">
          <span className="field-label">이 Skill로 할 수 있는 일 <span className="field-optional">한 줄에 하나 · 5개까지</span></span>
          <textarea value={draft.useCases} onChange={set('useCases')} rows={4} />
        </label>
        <label className="field">
          <span className="field-label">사용 예시 <span className="field-optional">한 줄에 하나 · 5개까지</span></span>
          <textarea value={draft.examplePrompts} onChange={set('examplePrompts')} rows={4} />
        </label>
      </div>
      <label className="field">
        추천 대상
        <input value={draft.recommendedFor} onChange={set('recommendedFor')} maxLength={LIMITS.recommendedFor} />
      </label>
      <div className="form-row">
        <label className="field">
          <span className="field-label">버전 <span className="field-optional">선택</span></span>
          <input value={draft.version} onChange={set('version')} maxLength={LIMITS.version} placeholder={versionPlaceholder} />
        </label>
        <label className="field">
          <span className="field-label">작성자 <span className="field-optional">선택 · AI 가 채우지 않습니다</span></span>
          <input value={draft.author} onChange={set('author')} maxLength={LIMITS.author} placeholder="예: 철도AI융합연구실" />
        </label>
      </div>
    </fieldset>
  )
}
