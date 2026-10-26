import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { api, ApiError } from '../api/client'
import Modal from '../components/Modal'
import type { EnrichmentSource, SkillDetail } from '../types/api'
import { draftFromSkill, draftFromSuggestion, draftToUpdate, type InfoDraft } from './infoDraft'
import { AiBadge, Analyzing } from './ShareInfo'
import SkillInfoFields from './SkillInfoForm'

// 상세 화면의 공유 정보 고치기. reanalyze 면 저장된 package 를 AI 로 다시 정리한 제안을 먼저 채운다.
// 어느 쪽이든 저장 전 사람이 확인하고, 저장해도 package 파일은 그대로다.
export default function EditShareInfoDialog({
  skill,
  reanalyze,
  onClose,
  onSaved,
}: {
  skill: SkillDetail
  reanalyze: boolean
  onClose: () => void
  onSaved: (s: SkillDetail) => void
}) {
  const [draft, setDraft] = useState<InfoDraft>(() => draftFromSkill(skill))
  // 저장할 정리 출처. 직접 고치면 기존 출처를 두고, 처음 쓰는 정보면 manual.
  const [source, setSource] = useState<EnrichmentSource>(skill.enrichment_source ?? 'manual')
  const [analyzing, setAnalyzing] = useState<{ startedAt: number } | null>(null)
  const [aiError, setAiError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const started = useRef(false)

  const { id, version, author } = skill
  const runAnalysis = useCallback(async () => {
    setAiError(null)
    setAnalyzing({ startedAt: performance.now() })
    try {
      const analysis = await api.reanalyzeSkill(id)
      // 버전 · 작성자는 AI 가 정하지 않는다. 지금 값을 둔다
      setDraft(draftFromSuggestion(analysis.suggestion, { version, author }))
      setSource(analysis.analysis_source)
    } catch (e) {
      const err = e as ApiError
      setAiError(err.status === 0 || err.status >= 500 ? 'AI 자동 정리에 실패했습니다. 다시 시도하거나 직접 고칠 수 있습니다.' : err.message)
    } finally {
      setAnalyzing(null)
    }
  }, [id, version, author])

  useEffect(() => {
    // StrictMode 의 effect 두 번 실행에서 분석을 두 번 부르지 않는다
    if (reanalyze && !started.current) {
      started.current = true
      void runAnalysis()
    }
  }, [reanalyze, runAnalysis])

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setSaving(true)
    setError(null)
    try {
      onSaved(await api.updateSkillInfo(skill.id, { ...draftToUpdate(draft), enrichment_source: source }))
    } catch (err) {
      setError((err as Error).message)
      setSaving(false)
    }
  }

  const busy = saving || analyzing !== null
  return (
    <Modal title={reanalyze ? 'AI로 다시 정리' : '공유 정보 수정'} onClose={onClose} busy={busy} wide>
      {analyzing ? (
        <Analyzing startedAt={analyzing.startedAt} />
      ) : (
        <form className="skill-form edit-share-form" onSubmit={save}>
          <div className="result-head">
            <p className="form-lead">
              Library 에 보이는 정보만 바꿉니다. 원본 Skill 파일 · Skill ID · 원본 description 은 그대로입니다.
            </p>
            <AiBadge source={source} />
          </div>
          {aiError && (
            <div className="analysis-failed" role="alert">
              <p>{aiError}</p>
              <div className="failed-actions">
                <button type="button" className="pill pill-outline" onClick={runAnalysis}>다시 시도</button>
              </div>
            </div>
          )}
          {source === 'mock' && reanalyze && <p className="notice">시험용 mock 정리 결과입니다. AI 모델이 연결되지 않은 환경입니다.</p>}
          <SkillInfoFields draft={draft} onChange={setDraft} disabled={busy} versionPlaceholder={`지금 v${skill.version}`} />
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="pill pill-outline" onClick={onClose} disabled={busy}>취소</button>
            <button type="submit" className="pill pill-primary" disabled={busy} aria-busy={saving}>
              {saving ? '저장하는 중…' : '저장'}
            </button>
          </div>
        </form>
      )}
    </Modal>
  )
}
