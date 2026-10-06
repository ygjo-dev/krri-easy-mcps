// 내 MCP(selection) 변경 신호. BFF 의 GET /api/toolbox/events (text/event-stream) 만 부른다 — Gateway 를 직접 부르지 않는다.
// 신호는 "다시 읽어라" 뿐이다. 받으면 기존 GET /api/toolbox 로 다시 읽는다.
// 끊기면 1s → 2s → 5s(상한) 간격으로 다시 잇고, 다시 이어지면 onReconnect 로 한 번 다시 읽게 한다
// (끊긴 동안 놓친 변경을 메운다). 실패를 화면에 띄우지 않는다.

const EVENTS_PATH = '/api/toolbox/events'
const RECONNECT_DELAYS_MS = [1000, 2000, 5000]
const CHANGED_EVENT = 'selection_changed'

export function subscribeToolboxChanges(onChange: () => void, onReconnect: () => void): () => void {
  const controller = new AbortController()
  let connectedBefore = false
  let attempt = 0

  const connect = async () => {
    const res = await fetch(EVENTS_PATH, {
      headers: { Accept: 'text/event-stream' },
      cache: 'no-store',
      signal: controller.signal,
    })
    if (!res.ok || !res.body) throw new Error(`toolbox events HTTP ${res.status}`)
    // 한 번이라도 끊겼거나 처음부터 못 열었으면, 그동안 놓친 변경을 메우게 한 번 다시 읽는다.
    if (connectedBefore || attempt > 0) onReconnect()
    connectedBefore = true
    attempt = 0
    await readEvents(res.body, (name) => {
      if (name === CHANGED_EVENT) onChange()
    })
  }

  const run = async () => {
    while (!controller.signal.aborted) {
      try {
        await connect()
      } catch {
        // 아래에서 기다렸다 다시 잇는다.
      }
      if (controller.signal.aborted) return
      const delay = RECONNECT_DELAYS_MS[Math.min(attempt, RECONNECT_DELAYS_MS.length - 1)]
      attempt += 1
      await wait(delay, controller.signal)
    }
  }

  void run()
  return () => controller.abort()
}

async function readEvents(body: ReadableStream<Uint8Array>, onEvent: (name: string) => void) {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) return
    buffer += decoder.decode(value, { stream: true })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() ?? ''
    for (const block of blocks) {
      const eventLine = block.split(/\r?\n/).find((line) => line.startsWith('event:'))
      if (eventLine) onEvent(eventLine.slice(6).trim())
    }
  }
}

function wait(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve) => {
    const timer = window.setTimeout(resolve, ms)
    signal.addEventListener(
      'abort',
      () => {
        window.clearTimeout(timer)
        resolve()
      },
      { once: true },
    )
  })
}
