import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DemoQuestion, Execution } from '../types/api'
import Json from './Json'

// 자유 입력 없음. 고정 질문만 고르고, 브라우저는 question_id 만 보낸다.
export default function TryWithAi({ serverId }: { serverId: string }) {
  const [questions, setQuestions] = useState<DemoQuestion[] | null>(null)
  const [running, setRunning] = useState<string | null>(null)
  const [result, setResult] = useState<Execution | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listDemoQuestions(serverId).then(setQuestions, (e: Error) => setError(e.message))
  }, [serverId])

  async function run(q: DemoQuestion) {
    setRunning(q.question_id)
    setResult(null)
    setError(null)
    try {
      setResult(await api.executeDemoQuestion(q.question_id))
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setRunning(null)
    }
  }

  if (!questions) return error ? <p className="error">{error}</p> : <p className="muted">불러오는 중…</p>
  if (questions.length === 0) return <p className="muted">준비된 질문이 없습니다.</p>

  return (
    <div className="try">
      <div className="questions">
        {questions.map((q) => (
          <button
            key={q.question_id}
            onClick={() => run(q)}
            disabled={running !== null}
            className={result?.question_id === q.question_id ? 'selected' : ''}
          >
            {running === q.question_id ? '실행 중…' : q.display_text}
          </button>
        ))}
      </div>
      {error && <p className="error">{error}</p>}
      {result && <ExecutionView result={result} />}
    </div>
  )
}

function ExecutionView({ result }: { result: Execution }) {
  return (
    <div className="execution">
      <h3>실행 결과</h3>
      <p className="muted">
        해석: {result.resolve_status ?? '—'}
        {result.matches_expected_recipe !== null &&
          ` · 예상 기능 ${result.matches_expected_recipe ? '일치' : '불일치'}`}
        {result.source === 'mock' && ' · mock'}
      </p>
      {result.steps.length === 0 ? (
        <p className="muted">호출된 Tool 이 없습니다.</p>
      ) : (
        <ol className="steps">
          {result.steps.map((s, i) => (
            <li key={`${s.node}-${i}`}>
              <div className="step-head">
                <code>{s.tool}</code>
                <span className={`badge badge-${s.status === 'success' ? 'online' : 'offline'}`}>
                  {s.status === 'success' ? '성공' : '실패'}
                </span>
              </div>
              <Json label="Request" value={s.request} />
              <Json label="Response" value={s.response} />
            </li>
          ))}
        </ol>
      )}
      <h3>최종 답변</h3>
      <p className="answer">{result.answer}</p>
      {result.limitations.map((l) => (
        <p key={l} className="notice">{l}</p>
      ))}
    </div>
  )
}
