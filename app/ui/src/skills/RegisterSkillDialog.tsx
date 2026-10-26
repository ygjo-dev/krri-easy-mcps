import { useState, type DragEvent, type FormEvent } from 'react'
import { api, ApiError, ShareIncompleteError } from '../api/client'
import Modal from '../components/Modal'
import type { EnrichmentSource, SkillAnalysis, SkillDetail } from '../types/api'
import { formatBytes } from './format'
import { draftFromSuggestion, draftToUpdate, splitTags, type InfoDraft } from './infoDraft'
import { AiBadge, Analyzing, ShareInfoSections } from './ShareInfo'
import { CompatBadges, TagList } from './SkillBits'
import SkillInfoFields from './SkillInfoForm'

type Mode = 'zip' | 'simple'
const ID_PATTERN = '[a-z0-9]+(-[a-z0-9]+)*'
const INSTRUCTIONS_PLACEHOLDER = `## 순서
1. 입력에서 … 을 찾는다.
2. … 형식으로 정리한다.

## 출력 형식
- …`

const EMPTY_DRAFT: InfoDraft = {
  title: '', summary: '', tags: '', useCases: '', recommendedFor: '', examplePrompts: '', version: '', author: '',
}

// ZIP 공유 단계. 분석 결과는 저장하지 않은 미리보기다 (새로 고치면 사라진다).
type Stage =
  | { kind: 'pick' }
  | { kind: 'analyzing'; startedAt: number }
  | { kind: 'failed'; message: string; aiFailed: boolean }
  | { kind: 'review'; analysis: SkillAnalysis | null; source: EnrichmentSource; seconds: number | null }

// 새 Skill 공유. 기본은 「ZIP으로 공유」(AI 자동 정리 → 검토 → 공유), 「직접 만들기」는 입력으로 SKILL.md 를 만든다.
export default function RegisterSkillDialog({ onClose, onCreated }: { onClose: () => void; onCreated: (s: SkillDetail) => void }) {
  const [mode, setMode] = useState<Mode>('zip')
  const [busy, setBusy] = useState(false)
  return (
    <Modal title="새 Skill 공유" onClose={onClose} busy={busy} wide>
      <div className="segmented" role="tablist" aria-label="공유 방식">
        <button type="button" role="tab" aria-selected={mode === 'zip'} onClick={() => setMode('zip')} disabled={busy}>
          ZIP으로 공유
        </button>
        <button type="button" role="tab" aria-selected={mode === 'simple'} onClick={() => setMode('simple')} disabled={busy}>
          직접 만들기
        </button>
      </div>
      {mode === 'zip' ? (
        <ZipShare busy={busy} setBusy={setBusy} onClose={onClose} onCreated={onCreated} />
      ) : (
        <SimpleCreate busy={busy} setBusy={setBusy} onClose={onClose} onCreated={onCreated} />
      )}
    </Modal>
  )
}

type StepProps = { busy: boolean; setBusy: (b: boolean) => void; onClose: () => void; onCreated: (s: SkillDetail) => void }

function isZip(file: File) {
  return /\.zip$/i.test(file.name) || file.type === 'application/zip' || file.type === 'application/x-zip-compressed'
}

// ── ZIP 으로 공유 (AI 자동 정리) ──────────────────────────────────────

function ZipShare({ busy, setBusy, onClose, onCreated }: StepProps) {
  const [file, setFile] = useState<File | null>(null)
  const [stage, setStage] = useState<Stage>({ kind: 'pick' })
  const [draft, setDraft] = useState<InfoDraft>(EMPTY_DRAFT)
  const [editing, setEditing] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [shareError, setShareError] = useState<{ message: string; skill: SkillDetail | null } | null>(null)

  const choose = (next: File | null) => {
    if (busy) return
    setFile(next)
    setStage({ kind: 'pick' })
    setShareError(null)
    if (next && !isZip(next)) setStage({ kind: 'failed', message: 'ZIP 파일(.zip)을 골라 주세요.', aiFailed: false })
  }

  const analyze = async () => {
    if (!file) return
    const startedAt = performance.now()
    setBusy(true)
    setShareError(null)
    setStage({ kind: 'analyzing', startedAt })
    try {
      const analysis = await api.analyzeSkill(file)
      setDraft(draftFromSuggestion(analysis.suggestion, analysis.package))
      setEditing(false)
      setStage({ kind: 'review', analysis, source: analysis.analysis_source, seconds: (performance.now() - startedAt) / 1000 })
    } catch (e) {
      const err = e as ApiError
      // 502 · 연결 실패 = AI 정리 실패 (package 는 통과). 400 · 413 = package 문제 → 다른 파일을 골라야 한다
      setStage({ kind: 'failed', message: err.message, aiFailed: err.status === 0 || err.status >= 500 })
    } finally {
      setBusy(false)
    }
  }

  const manual = () => {
    setDraft(EMPTY_DRAFT)
    setEditing(true)
    setStage({ kind: 'review', analysis: null, source: 'manual', seconds: null })
  }

  const share = async (e: FormEvent) => {
    e.preventDefault()
    if (!file || stage.kind !== 'review') return
    setBusy(true)
    setShareError(null)
    try {
      onCreated(await api.createSkillFromPackage(file, { ...draftToUpdate(draft), enrichment_source: stage.source }))
    } catch (err) {
      setShareError({
        message: (err as Error).message,
        skill: err instanceof ShareIncompleteError ? err.skill : null,
      })
      setBusy(false)
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    choose(e.dataTransfer.files?.[0] ?? null)
  }

  if (stage.kind === 'review') {
    const { analysis, source } = stage
    const info = draftToUpdate(draft)
    return (
      <form className="skill-form share-review" onSubmit={share}>
        <div className="result-head">
          <div>
            <h3>{source === 'manual' ? '공유 정보 직접 입력' : 'AI 자동 정리 결과'}</h3>
            <p className="form-lead">
              {source === 'manual'
                ? 'Library 에 보일 제목 · 요약 · 태그 · 활용 예시를 입력하세요. 원본 Skill 파일은 바꾸지 않습니다.'
                : '확인하고 필요하면 고친 뒤 공유하세요. 원본 Skill 파일은 바꾸지 않습니다.'}
            </p>
          </div>
          {source !== 'manual' && (
            <div className="result-head-side">
              <AiBadge source={source} />
              {stage.seconds !== null && <span className="result-time">{stage.seconds.toFixed(1)}초</span>}
            </div>
          )}
        </div>
        {source === 'mock' && <p className="notice">시험용 mock 정리 결과입니다. AI 모델이 연결되지 않은 환경입니다.</p>}

        {editing ? (
          <SkillInfoFields draft={draft} onChange={setDraft} disabled={busy} versionPlaceholder="비우면 1.0.0" />
        ) : (
          <article className="result-card" aria-label="공유될 모습 미리보기">
            <h4 className="result-title">{info.title || analysis?.package.id}</h4>
            <p className="result-summary">{info.summary || analysis?.package.description}</p>
            <TagList tags={splitTags(draft.tags)} />
            <ShareInfoSections useCases={info.use_cases} recommendedFor={info.recommended_for || null}
              examplePrompts={info.example_prompts} />
          </article>
        )}

        {analysis && <PackageFacts analysis={analysis} />}

        {shareError && (
          <div className="form-error" role="alert">
            <p>{shareError.message}</p>
            {shareError.skill && (
              <button type="button" className="link-button" onClick={() => onCreated(shareError.skill as SkillDetail)}>
                등록된 Skill 보기
              </button>
            )}
          </div>
        )}
        <div className="modal-actions review-actions">
          <button type="button" className="link-button" onClick={() => choose(null)} disabled={busy}>다른 파일 고르기</button>
          <span className="actions-spacer" />
          {source !== 'manual' && (
            <button type="button" className="pill pill-outline" onClick={() => setEditing((v) => !v)} disabled={busy}
              aria-pressed={editing}>
              {editing ? '미리보기' : '내용 수정'}
            </button>
          )}
          <button type="submit" className="pill pill-primary" disabled={busy} aria-busy={busy}>
            {busy ? '공유하는 중…' : '이 내용으로 공유'}
          </button>
        </div>
      </form>
    )
  }

  return (
    <div className="skill-form">
      <div className="share-lead">
        <p><strong>Skill ZIP 하나만 올려보세요.</strong></p>
        <p>AI가 Skill의 내용을 읽고 공유에 필요한 제목, 설명, 태그와 활용 예시를 자동으로 정리합니다.</p>
        <p className="muted">원본 Skill 파일은 수정하지 않습니다. 서버는 script 를 실행하지 않습니다.</p>
      </div>

      <label
        className={`dropzone${dragging ? ' dropzone-over' : ''}${file ? ' dropzone-filled' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          if (!busy) setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        aria-disabled={busy}
      >
        <input
          type="file"
          accept=".zip,application/zip"
          className="visually-hidden"
          onChange={(e) => choose(e.target.files?.[0] ?? null)}
          disabled={busy}
          aria-label="Skill ZIP 파일"
        />
        <span className="dropzone-icon" aria-hidden="true">⇪</span>
        {file ? (
          <span className="dropzone-file">
            <strong className="mono">{file.name}</strong>
            <span className="muted">{formatBytes(file.size)} · 다른 파일을 고르려면 누르세요</span>
          </span>
        ) : (
          <span className="dropzone-file">
            <strong>ZIP 파일을 끌어다 놓거나 눌러서 고르세요</strong>
            <span className="muted">skill folder 안에 SKILL.md (frontmatter name · description) 가 있어야 합니다</span>
          </span>
        )}
      </label>

      {stage.kind === 'analyzing' && <Analyzing startedAt={stage.startedAt} />}

      {stage.kind === 'failed' && (
        <div className="analysis-failed" role="alert">
          <strong>{stage.aiFailed ? 'AI 자동 정리에 실패했습니다.' : 'Skill package 를 확인해 주세요.'}</strong>
          <p>{stage.aiFailed ? '다시 시도하거나 직접 정보를 입력해서 등록할 수 있습니다.' : stage.message}</p>
          {stage.aiFailed && (
            <div className="failed-actions">
              <button type="button" className="pill pill-outline" onClick={analyze}>다시 시도</button>
              <button type="button" className="pill pill-outline" onClick={manual}>직접 입력해서 등록</button>
            </div>
          )}
        </div>
      )}

      <div className="modal-actions review-actions">
        {file && stage.kind === 'pick' && (
          <button type="button" className="link-button" onClick={manual}>AI 없이 직접 입력</button>
        )}
        <span className="actions-spacer" />
        <button type="button" className="pill pill-outline" onClick={onClose} disabled={busy}>취소</button>
        <button type="button" className="pill pill-primary pill-ai" onClick={analyze}
          disabled={!file || busy || (stage.kind === 'failed' && !stage.aiFailed)} aria-busy={busy}>
          <span aria-hidden="true">✦</span> {busy ? '정리하는 중…' : 'AI로 자동 정리'}
        </button>
      </div>
    </div>
  )
}

// 원본 package 정보. AI 가 만든 값이 아니다.
function PackageFacts({ analysis }: { analysis: SkillAnalysis }) {
  const pkg = analysis.package
  return (
    <details className="package-facts">
      <summary>
        <span>원본 Skill</span>
        <code className="skill-id">{pkg.id}</code>
        <span className="muted">파일 {pkg.file_count}개 · {formatBytes(pkg.total_bytes)}</span>
        <CompatBadges compat={pkg.compat} />
      </summary>
      <dl>
        <dt>원본 설명</dt>
        <dd>{pkg.description}</dd>
        {pkg.version && (<><dt>버전</dt><dd>{pkg.version}</dd></>)}
        {pkg.author && (<><dt>작성자</dt><dd>{pkg.author}</dd></>)}
      </dl>
      {pkg.warnings.length > 0 && (
        <ul className="facts-warnings">
          {pkg.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </details>
  )
}

// ── 직접 만들기 (입력 → SKILL.md 생성) ───────────────────────────────

function SimpleCreate({ busy, setBusy, onClose, onCreated }: StepProps) {
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({
    title: '', id: '', description: '', version: '1.0.0', author: '', tags: '', instructions: '', example: '',
  })
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await api.createSkill({
        id: form.id, title: form.title, description: form.description, version: form.version, author: form.author,
        tags: splitTags(form.tags), instructions: form.instructions, example: form.example,
      }))
    } catch (err) {
      setError((err as Error).message)
      setBusy(false)
    }
  }

  return (
    <form className="skill-form" onSubmit={onSubmit}>
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
      <div className="form-row form-row-3">
        <label className="field">
          버전
          <input value={form.version} onChange={set('version')} maxLength={25} />
        </label>
        <label className="field">
          작성자
          <input value={form.author} onChange={set('author')} maxLength={100} placeholder="예: 철도AI융합연구실" />
        </label>
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
  )
}
