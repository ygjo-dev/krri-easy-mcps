import { useState } from 'react'
import type { DemoRun } from '../demo/useDemoRun'
import { ChevronIcon } from './Icons'

// PlayMCP AI 채팅 panel 의 배치를 따른다: 머리 · 대화(질문 말풍선 → TOOL 호출 → 답) · 아래 「대화 예시」.
// 자유 입력창은 두지 않는다. 준비된 질문만 실행한다.
export default function AiPanel({ demo, mcpName }: { demo: DemoRun; mcpName: string }) {
  const [toolsOpen, setToolsOpen] = useState(true)
  const [examplesOpen, setExamplesOpen] = useState(true)
  const { questions, questionsError, asked, running, result, error, run, reset } = demo

  return (
    <aside className="ai-panel" aria-label="AI로 사용해보기">
      <header className="ai-head">
        <strong>AI로 사용해보기</strong>
        <button type="button" className="pill pill-panel" onClick={reset} disabled={!asked || running}>
          + 새 대화
        </button>
      </header>

      <div className="ai-body" aria-live="polite">
        {!asked && (
          <div className="ai-intro">
            <p>아래 대화 예시를 누르면 AI 가 이 MCP 의 Tool 을 어떻게 쓰는지 볼 수 있습니다.</p>
          </div>
        )}
        {asked && <p className="bubble-user">{asked.display_text}</p>}
        {asked && running && (
          <div className="tool-calls">
            <p className="tool-calls-title">TOOL 호출</p>
            <p className="ai-pending">실행 중<span className="dots" aria-hidden="true" /></p>
          </div>
        )}
        {result && result.steps.length > 0 && (
          <div className="tool-calls">
            <button type="button" className="tool-calls-title" aria-expanded={toolsOpen} onClick={() => setToolsOpen((v) => !v)}>
              TOOL 호출 <span className="muted">{result.steps.length}</span>
              <ChevronIcon />
            </button>
            {toolsOpen && (
              <ol className="tool-steps">
                {result.steps.map((s, i) => (
                  <li key={`${s.node}-${i}`} className={`step-${s.status}`}>
                    <span className="step-mark" aria-hidden="true">{s.status === 'success' ? '✓' : '!'}</span>
                    <span className="step-text">
                      <code>{s.tool}</code>
                      <span className="step-sub">{mcpName} · {s.status === 'success' ? '성공' : '실패'}</span>
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>
        )}
        {result && <p className="ai-answer">{result.answer}</p>}
        {result?.source === 'mock' && <p className="ai-note">.</p>}
        {error && <p className="ai-error" role="alert">{error}</p>}
      </div>

      <footer className="ai-examples">
        <button type="button" className="ai-examples-toggle" aria-expanded={examplesOpen} onClick={() => setExamplesOpen((v) => !v)}>
          대화 예시
          <ChevronIcon />
        </button>
        {examplesOpen && (
          <>
            {questionsError && <p className="ai-error">{questionsError}</p>}
            {!questions && !questionsError && <p className="ai-muted">불러오는 중…</p>}
            {questions && questions.length === 0 && <p className="ai-muted">이 MCP 에는 준비된 대화 예시가 아직 없습니다.</p>}
            {questions && questions.length > 0 && (
              <ul className="ai-questions">
                {questions.map((q) => (
                  <li key={q.question_id}>
                    <button
                      type="button"
                      onClick={() => run(q)}
                      disabled={running}
                      aria-pressed={asked?.question_id === q.question_id}
                    >
                      {q.display_text}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </footer>
    </aside>
  )
}
