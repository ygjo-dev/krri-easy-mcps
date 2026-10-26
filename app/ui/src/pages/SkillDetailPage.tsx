import { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import Modal from '../components/Modal'
import AdminGate from '../skills/AdminGate'
import EditShareInfoDialog from '../skills/EditShareInfoDialog'
import { formatBytes, formatDateTime, saveBlob, stripFrontmatter } from '../skills/format'
import InstallGuide from '../skills/InstallGuide'
import MarkdownPreview from '../skills/MarkdownPreview'
import { AiBadge, ShareInfoSections } from '../skills/ShareInfo'
import { CompatBadges, SkillIcon, TagList } from '../skills/SkillBits'
import type { SkillDetail, SkillTarget } from '../types/api'

export default function SkillDetailPage() {
  const { skillId = '' } = useParams()
  return (
    <AdminGate>
      <SkillDetailView key={skillId} skillId={skillId} />
    </AdminGate>
  )
}

type Tab = 'skill' | 'files' | 'examples'
type ProductTarget = Exclude<SkillTarget, 'source'>

function SkillDetailView({ skillId }: { skillId: string }) {
  const navigate = useNavigate()
  // 방금 공유한 Skill 이면 (등록 창에서 넘어옴) 한 번 알린다
  const location = useLocation()
  const [justShared] = useState(() => Boolean((location.state as { shared?: boolean } | null)?.shared))
  const [editing, setEditing] = useState<'edit' | 'reanalyze' | null>(null)
  const [skill, setSkill] = useState<SkillDetail | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [tab, setTab] = useState<Tab>('skill')
  const [raw, setRaw] = useState(false)
  const [downloading, setDownloading] = useState<SkillTarget | null>(null)
  const [downloadError, setDownloadError] = useState<string | null>(null)
  const [guide, setGuide] = useState<{ target: ProductTarget; filename: string } | null>(null)

  useEffect(() => {
    api.getSkill(skillId).then(setSkill, (e: ApiError) => setError(e))
  }, [skillId])

  const download = async (target: SkillTarget) => {
    setDownloading(target)
    setDownloadError(null)
    try {
      const { blob, filename } = await api.downloadSkill(skillId, target)
      saveBlob(blob, filename)
      if (target !== 'source') setGuide({ target, filename })
    } catch (e) {
      setDownloadError((e as Error).message)
    } finally {
      setDownloading(null)
    }
  }

  if (error) {
    return (
      <div className="state-block" role="alert">
        <p>{error.status === 404 ? 'Skill 을 찾을 수 없습니다.' : error.message}</p>
        <Link to="/skills" className="pill pill-outline">AI Skills 로</Link>
      </div>
    )
  }
  if (!skill) return <div className="state-block muted">Skill 정보를 불러오는 중…</div>

  return (
    <>
      <nav className="breadcrumb" aria-label="위치">
        <Link to="/skills">AI Skills</Link>
        <span aria-hidden="true">›</span>
        <span aria-current="page">{skill.title}</span>
      </nav>

      {justShared && (
        <p className="shared-notice" role="status">
          AI Skills Library 에 공유했습니다. 구성원이 검색해서 찾고, ChatGPT · Claude 용 ZIP 을 받아 쓸 수 있습니다.
        </p>
      )}

      <div className="detail-layout">
        <div className="detail-main">
          <div className="detail-identity">
            <SkillIcon id={skill.id} title={skill.title} size="lg" />
            <div>
              <h1>{skill.title}</h1>
              <div className="skill-id-row">
                <code className="skill-id">{skill.id}</code>
                <CompatBadges compat={skill.compat} />
                <AiBadge source={skill.enrichment_source} />
              </div>
            </div>
          </div>

          <dl className="stats">
            <div><dt>버전</dt><dd>v{skill.version}</dd></div>
            <div><dt>작성자</dt><dd>{skill.author || '—'}</dd></div>
            <div><dt>파일</dt><dd>{skill.file_count}개</dd></div>
            <div><dt>업데이트</dt><dd className="stats-small">{formatDateTime(skill.updated_at)}</dd></div>
          </dl>

          {/* 공유용 요약(AI 자동 정리 + 검토). 없으면 원본 description */}
          <p className="detail-summary">{skill.summary || skill.description}</p>
          <TagList tags={skill.tags} />

          <section className="detail-section share-section" aria-label="공유 정보">
            <ShareInfoSections useCases={skill.use_cases} recommendedFor={skill.recommended_for}
              examplePrompts={skill.example_prompts} />
            {!skill.summary && skill.use_cases.length === 0 && skill.example_prompts.length === 0 && (
              <p className="section-note share-empty">
                아직 AI 자동 정리 전인 Skill 입니다. 「AI로 정리하기」를 누르면 할 수 있는 일 · 추천 대상 · 사용 예시를 정리합니다.
              </p>
            )}
            {skill.summary && (
              <div className="original-desc">
                <span>원본 Skill 설명 <span className="muted">SKILL.md frontmatter</span></span>
                <p>{skill.description}</p>
              </div>
            )}
            <div className="share-actions">
              <button type="button" className="pill pill-ghost" onClick={() => setEditing('reanalyze')}>
                <span aria-hidden="true">✦</span> {skill.enrichment_source === 'live' || skill.enrichment_source === 'mock' ? 'AI로 다시 정리' : 'AI로 정리하기'}
              </button>
              <button type="button" className="pill pill-ghost" onClick={() => setEditing('edit')}>공유 정보 수정</button>
            </div>
          </section>
          {/* 좁은 화면에서는 오른쪽 칸 대신 여기 (긴 미리보기 아래로 밀리지 않게) */}
          <div className="add-inline">
            <AddPanel skill={skill} downloading={downloading} error={downloadError} onDownload={download} />
          </div>

          {skill.warnings.length > 0 && (
            <div className="notice skill-warnings">
              <strong>확인할 점</strong>
              <ul>
                {skill.warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="tabs" role="tablist">
            <button type="button" role="tab" aria-selected={tab === 'skill'} onClick={() => setTab('skill')}>SKILL.md</button>
            <button type="button" role="tab" aria-selected={tab === 'files'} onClick={() => setTab('files')}>
              포함 파일 <span className="muted">{skill.files.length}</span>
            </button>
            {skill.examples.length > 0 && (
              <button type="button" role="tab" aria-selected={tab === 'examples'} onClick={() => setTab('examples')}>
                사용 예시 <span className="muted">{skill.examples.length}</span>
              </button>
            )}
          </div>

          {tab === 'skill' && (
            <section className="detail-section skill-doc">
              <div className="skill-doc-head">
                <span className="mono">{skill.main_file}</span>
                <div className="segmented segmented-sm" role="group" aria-label="보기 방식">
                  <button type="button" aria-pressed={!raw} onClick={() => setRaw(false)}>미리보기</button>
                  <button type="button" aria-pressed={raw} onClick={() => setRaw(true)}>원문</button>
                </div>
              </div>
              {raw ? <pre className="md-raw">{skill.skill_md}</pre> : <MarkdownPreview text={stripFrontmatter(skill.skill_md)} />}
            </section>
          )}
          {tab === 'files' && (
            <section className="detail-section">
              <p className="section-note">ChatGPT · Claude 용 ZIP 에 같은 파일이 들어갑니다. 서버는 script 를 실행하지 않습니다.</p>
              <ul className="file-list">
                {skill.files.map((f) => (
                  <li key={f.path}>
                    <span className="mono file-path">{f.path}</span>
                    <span className="muted">{formatBytes(f.size)}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
          {tab === 'examples' && (
            <div className="example-list">
              {skill.examples.map((ex) => (
                <section key={ex.path} className="detail-section">
                  <h2 className="mono">{ex.path}</h2>
                  <pre className="md-raw">{ex.content}</pre>
                </section>
              ))}
            </div>
          )}

          <ManageSkill skill={skill} onUpdated={setSkill} onDeleted={() => navigate('/skills')} />
        </div>

        <aside className="detail-side skill-side">
          <AddPanel skill={skill} downloading={downloading} error={downloadError} onDownload={download} />
        </aside>
      </div>

      {editing && (
        <EditShareInfoDialog
          skill={skill}
          reanalyze={editing === 'reanalyze'}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setSkill(updated)
            setEditing(null)
          }}
        />
      )}
      {guide && (
        <InstallGuide target={guide.target} filename={guide.filename} onAgain={() => download(guide.target)} onClose={() => setGuide(null)} />
      )}
    </>
  )
}

// 관리: 새 버전 ZIP 올리기 · 삭제. 비운 표시 정보는 이전 값을 그대로 쓴다.
function ManageSkill({ skill, onUpdated, onDeleted }: { skill: SkillDetail; onUpdated: (s: SkillDetail) => void; onDeleted: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null)
  const [version, setVersion] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null)

  const upload = async (file: File) => {
    setBusy(true)
    setMessage(null)
    try {
      const updated = await api.uploadSkillVersion(skill.id, file, { version })
      onUpdated(updated)
      setVersion('')
      setMessage({ error: false, text: `v${updated.version} 으로 바꿨습니다. 내용이 바뀌었으면 위의 「AI로 다시 정리」로 공유 정보를 고치세요.` })
    } catch (e) {
      setMessage({ error: true, text: (e as Error).message })
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const remove = async () => {
    setBusy(true)
    try {
      await api.deleteSkill(skill.id)
      onDeleted()
    } catch (e) {
      setMessage({ error: true, text: (e as Error).message })
      setBusy(false)
      setConfirming(false)
    }
  }

  return (
    <section className="manage-skill" aria-label="관리">
      <h2>관리</h2>
      <p className="section-note">
        새 버전은 같은 Skill ID(frontmatter <code>name</code>) 의 ZIP 이어야 합니다. 처음 등록: {formatDateTime(skill.created_at)}
      </p>
      <div className="manage-row">
        <label className="field manage-version">
          새 버전 번호
          <input value={version} onChange={(e) => setVersion(e.target.value)} placeholder={`지금 v${skill.version}`} maxLength={25} disabled={busy} />
        </label>
        <input ref={fileRef} type="file" accept=".zip,application/zip" hidden
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        <button type="button" className="pill pill-outline" onClick={() => fileRef.current?.click()} disabled={busy}>
          {busy ? '처리 중…' : '새 버전 ZIP 올리기'}
        </button>
        <button type="button" className="pill pill-danger" onClick={() => setConfirming(true)} disabled={busy}>삭제</button>
      </div>
      {message && <p className={message.error ? 'form-error' : 'form-ok'} role={message.error ? 'alert' : 'status'}>{message.text}</p>}
      {confirming && (
        <Modal title="Skill 삭제" onClose={() => setConfirming(false)} busy={busy}>
          <p className="install-lead">「{skill.title}」 를 library 에서 삭제합니다. 이미 ChatGPT · Claude 에 올린 Skill 은 그대로 남습니다. 되돌릴 수 없습니다.</p>
          <div className="modal-actions">
            <button type="button" className="pill pill-outline" onClick={() => setConfirming(false)} disabled={busy}>취소</button>
            <button type="button" className="pill pill-danger" onClick={remove} disabled={busy} aria-busy={busy}>
              {busy ? '삭제 중…' : '삭제'}
            </button>
          </div>
        </Modal>
      )}
    </section>
  )
}

// 「AI에 추가」: 내려받기만 한다. 설치는 각 서비스에서 사용자가 직접 한다.
function AddPanel({ skill, downloading, error, onDownload }: {
  skill: SkillDetail
  downloading: SkillTarget | null
  error: string | null
  onDownload: (target: SkillTarget) => void
}) {
  return (
    <section className="ai-panel add-panel" aria-label="AI에 추가">
      <div className="add-panel-body">
        <strong className="add-title">AI에 추가</strong>
        <p className="add-lead">
          Skill 을 ZIP 으로 내려받아 ChatGPT 또는 Claude 의 Skills 화면에 직접 올립니다. 내용은 두 서비스가 같습니다.
        </p>
        <button type="button" className="add-button" onClick={() => onDownload('chatgpt')} disabled={downloading !== null}
          aria-busy={downloading === 'chatgpt'}>
          <span>ChatGPT용 ZIP 다운로드</span>
          <small>{downloading === 'chatgpt' ? '내려받는 중…' : 'ZIP 내려받기 + 추가 안내'}</small>
        </button>
        <button type="button" className="add-button" onClick={() => onDownload('claude')} disabled={downloading !== null}
          aria-busy={downloading === 'claude'}>
          <span>Claude용 ZIP 다운로드</span>
          <small>{downloading === 'claude' ? '내려받는 중…' : 'ZIP 내려받기 + 추가 안내'}</small>
        </button>
        {!skill.compat.claude && <p className="add-warn">Claude 형식 확인이 필요합니다. 「확인할 점」을 보세요.</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <button type="button" className="link-button add-source" onClick={() => onDownload('source')} disabled={downloading !== null}>
          원본 패키지 다운로드
        </button>
      </div>
    </section>
  )
}
