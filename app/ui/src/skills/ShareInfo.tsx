import { useEffect, useState } from 'react'
import type { EnrichmentSource } from '../types/api'

// AI 가 정리한 공유 정보임을 작게 알린다. 사람이 직접 쓴 정보(manual)와 정리 전(null)에는 없다.
export function AiBadge({ source }: { source: EnrichmentSource | null }) {
  if (source !== 'live' && source !== 'mock') return null
  return (
    <span className="ai-badge" title={source === 'mock' ? '시험용 mock 정리 결과 (AI 모델 미연결)' : 'AI 가 Skill 내용을 읽고 정리한 뒤 사람이 검토한 정보'}>
      <span aria-hidden="true">✦</span> AI 자동 정리{source === 'mock' && ' · mock'}
    </span>
  )
}

// 클립보드 복사. LAN http 는 secure context 가 아니라 navigator.clipboard 가 없을 수 있다 → textarea 로 대신한다.
async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // 아래 방식으로
  }
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  const ok = document.execCommand('copy')
  area.remove()
  return ok
}

function PromptItem({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <li className="prompt-item">
      <span className="prompt-text">{text}</span>
      <button
        type="button"
        className="prompt-copy"
        onClick={async () => {
          if (await copyText(text)) {
            setCopied(true)
            window.setTimeout(() => setCopied(false), 1500)
          }
        }}
        aria-label={`「${text}」 복사`}
      >
        {copied ? '복사됨' : '복사'}
      </button>
    </li>
  )
}

// 「이 Skill로 할 수 있는 일 · 추천 대상 · 사용 예시」. 상세 화면과 등록 미리보기가 같이 쓴다. 비어 있는 칸은 그리지 않는다.
export function ShareInfoSections({
  useCases,
  recommendedFor,
  examplePrompts,
}: {
  useCases: string[]
  recommendedFor: string | null
  examplePrompts: string[]
}) {
  if (useCases.length === 0 && !recommendedFor && examplePrompts.length === 0) return null
  return (
    <div className="share-info">
      {useCases.length > 0 && (
        <section className="share-block">
          <h3>이 Skill로 할 수 있는 일</h3>
          <ul className="use-case-list">
            {useCases.map((u) => (
              <li key={u}>{u}</li>
            ))}
          </ul>
        </section>
      )}
      {recommendedFor && (
        <section className="share-block">
          <h3>추천 대상</h3>
          <p className="share-text">{recommendedFor}</p>
        </section>
      )}
      {examplePrompts.length > 0 && (
        <section className="share-block">
          <h3>사용 예시 <span className="share-hint">AI 에게 이렇게 요청해 보세요</span></h3>
          <ul className="prompt-list">
            {examplePrompts.map((p) => (
              <PromptItem key={p} text={p} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

// 서버가 단계별 진행을 알려 주지 않는다. 가짜 진행률 없이, 기다리는 일과 실제 흐른 시간만 보인다.
export function Analyzing({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(() => performance.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(performance.now()), 500)
    return () => window.clearInterval(timer)
  }, [])
  return (
    <div className="analyzing" role="status" aria-live="polite" aria-busy="true">
      <span className="spinner" aria-hidden="true" />
      <div>
        <strong>AI가 Skill 내용을 분석하고 있습니다…</strong>
        <p>SKILL.md · 참고 문서 · 예시를 읽고 제목 · 요약 · 태그 · 활용 예시를 정리합니다.</p>
      </div>
      <span className="analyzing-time">{Math.max(0, (now - startedAt) / 1000).toFixed(0)}초</span>
    </div>
  )
}
