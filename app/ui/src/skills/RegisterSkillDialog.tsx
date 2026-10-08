import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import Modal from '../components/Modal'
import type { SkillDetail } from '../types/api'

type Mode = 'simple' | 'zip'
const ID_PATTERN = '[a-z0-9]+(-[a-z0-9]+)*'
const INSTRUCTIONS_PLACEHOLDER = `## 순서
1. 입력에서 … 을 찾는다.
2. … 형식으로 정리한다.

## 출력 형식
- …`

function splitTags(value: string): string[] {
  return value.split(',').map((t) => t.trim()).filter(Boolean)
}

// 새 Skill 등록. 「간단히 만들기」(입력 → SKILL.md 생성) 또는 「ZIP 업로드」(이미 만든 skill folder).
export default function RegisterSkillDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (s: SkillDetail) => void }) {
  const [mode, setMode] = useState<Mode>('simple')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    title: '', id: '', description: '', version: '1.0.0', zipVersion: '', author: '', zipAuthor: '', tags: '',
    instructions: '', example: '',
  })
  const [file, setFile] = useState<File | null>(null)
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const created =
        mode === 'simple'
          ? await api.createSkill({
              id: form.id, title: form.title, description: form.description, version: form.version, author: form.author,
              tags: splitTags(form.tags), instructions: form.instructions, example: form.example,
            })
          : await api.uploadSkill(file as File, {
              title: form.title, version: form.zipVersion, author: form.zipAuthor, tags: form.tags,
            })
      onCreated(created)
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <Modal title="새 Skill 등록" onClose={onClose} busy={busy} wide>
      <div className="segmented" role="tablist" aria-label="등록 방식">
        <button type="button" role="tab" aria-selected={mode === 'simple'} onClick={() => setMode('simple')} disabled={busy}>
          간단히 만들기
        </button>
        <button type="button" role="tab" aria-selected={mode === 'zip'} onClick={() => setMode('zip')} disabled={busy}>
          ZIP 업로드
        </button>
      </div>
      <form className="skill-form" onSubmit={onSubmit}>
        {mode === 'simple' ? (
          <>
            <p className="form-lead">입력한 내용으로 ChatGPT · Claude 가 읽는 SKILL.md 를 만듭니다.</p>
            <div className="form-row">
              <label className="field">
                표시 이름
                <input value={form.title} onChange={set('title')} placeholder="예: 회의 내용 정리 (예시)" maxLength={100} required />
              </label>
              <label className="field">
                Skill ID
                <input
                  value={form.id}
                  onChange={set('id')}
                  placeholder="예: meeting-notes"
                  pattern={ID_PATTERN}
                  maxLength={64}
                  autoCapitalize="none"
                  spellCheck={false}
                  required
                />
                <span className="field-hint">영문 소문자 · 숫자 · 하이픈(-). ZIP 폴더 이름이 됩니다.</span>
              </label>
            </div>
            <label className="field">
              설명
              <textarea value={form.description} onChange={set('description')} rows={2} maxLength={1024} required
                placeholder="무엇을 하는 Skill 이고 언제 쓰는지. AI 는 이 문장을 보고 Skill 을 고릅니다." />
            </label>
            <label className="field">
              지시사항 (Markdown)
              <textarea value={form.instructions} onChange={set('instructions')} rows={8} required placeholder={INSTRUCTIONS_PLACEHOLDER}
                className="mono-input" />
            </label>
            <label className="field">
              <span className="field-label">사용 예시 <span className="field-optional">선택</span></span>
              <textarea value={form.example} onChange={set('example')} rows={3} placeholder="입력과 기대하는 출력 예시. examples/example.md 로 들어갑니다." />
            </label>
          </>
        ) : (
          <>
            <p className="form-lead">
              skill folder 를 압축한 ZIP 을 올립니다. folder 안에 <code>SKILL.md</code> (frontmatter <code>name</code> ·{' '}
              <code>description</code>) 가 있어야 하고, references · assets · scripts 등 다른 파일은 그대로 보관됩니다.
              서버는 script 를 실행하지 않습니다.
            </p>
            <label className="field file-field">
              ZIP 파일
              <input type="file" accept=".zip,application/zip" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
            </label>
            <label className="field">
              <span className="field-label">표시 이름 <span className="field-optional">선택 · 비우면 Skill ID</span></span>
              <input value={form.title} onChange={set('title')} maxLength={100} />
            </label>
          </>
        )}
        <div className="form-row form-row-3">
          {mode === 'simple' ? (
            <label className="field">
              버전
              <input value={form.version} onChange={set('version')} maxLength={25} />
            </label>
          ) : (
            <label className="field">
              <span className="field-label">버전 <span className="field-optional">선택</span></span>
              <input value={form.zipVersion} onChange={set('zipVersion')} maxLength={25} placeholder="비우면 SKILL.md metadata" />
            </label>
          )}
          {mode === 'simple' ? (
            <label className="field">
              작성자
              <input value={form.author} onChange={set('author')} maxLength={100} placeholder="예: 철도AI융합연구실" />
            </label>
          ) : (
            <label className="field">
              <span className="field-label">작성자 <span className="field-optional">선택</span></span>
              <input value={form.zipAuthor} onChange={set('zipAuthor')} maxLength={100} placeholder="비우면 SKILL.md metadata" />
            </label>
          )}
          <label className="field">
            <span className="field-label">태그 <span className="field-optional">쉼표로 구분</span></span>
            <input value={form.tags} onChange={set('tags')} placeholder="예: 문서작성, 검토" />
          </label>
        </div>
        {error && <p className="form-error" role="alert">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="pill pill-outline" onClick={onClose} disabled={busy}>취소</button>
          <button type="submit" className="pill pill-primary" disabled={busy} aria-busy={busy}>
            {busy ? '등록 중…' : '등록'}
          </button>
        </div>
      </form>
    </Modal>
  )
}
