import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import type { DemoQuestion, Execution } from '../types/api'

export interface DemoRun {
  questions: DemoQuestion[] | null
  questionsError: string | null
  asked: DemoQuestion | null
  running: boolean
  result: Execution | null
  error: string | null
  run: (q: DemoQuestion) => void
  reset: () => void
}

// 고정 질문 실행 상태. AI panel 과 「MCP 정보」 탭의 대화 예시가 같이 쓴다.
export function useDemoRun(serverId: string): DemoRun {
  const [questions, setQuestions] = useState<DemoQuestion[] | null>(null)
  const [questionsError, setQuestionsError] = useState<string | null>(null)
  const [asked, setAsked] = useState<DemoQuestion | null>(null)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<Execution | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.listDemoQuestions(serverId).then(setQuestions, (e: Error) => setQuestionsError(e.message))
  }, [serverId])

  const run = useCallback((q: DemoQuestion) => {
    setAsked(q)
    setRunning(true)
    setResult(null)
    setError(null)
    api
      .executeDemoQuestion(q.question_id)
      .then(setResult, (e: Error) => setError(e.message))
      .finally(() => setRunning(false))
  }, [])

  const reset = useCallback(() => {
    setAsked(null)
    setResult(null)
    setError(null)
  }, [])

  return { questions, questionsError, asked, running, result, error, run, reset }
}
