import { useState, type FormEvent } from 'react'
import { api } from '../api/client'
import Json from '../components/Json'
import MockNotice from '../components/MockNotice'
import type { InspectResult } from '../types/api'

// Endpoint 는 BFF 로만 보낸다. 브라우저가 입력된 endpoint 를 직접 부르지 않는다.
export default function RegisterPage() {
  const [endpoint, setEndpoint] = useState('')
  const [loading, setLoading] = useState(false)
  const [preview, setPreview] = useState<InspectResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setLoading(true)
    setPreview(null)
    setError(null)
    try {
      setPreview(await api.inspectEndpoint(endpoint))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section>
      <p className="muted">도구함</p>
      <h1>MCP 등록</h1>
      <form className="register" onSubmit={submit}>
        <label htmlFor="endpoint">MCP Endpoint</label>
        <div className="filters">
          <input
            id="endpoint"
            type="url"
            placeholder="https://example.org/mcp"
            value={endpoint}
            onChange={(e) => setEndpoint(e.target.value)}
            required
          />
          <button type="submit" disabled={loading}>{loading ? '불러오는 중…' : '정보 불러오기'}</button>
        </div>
      </form>
      {error && <p className="error">{error}</p>}
      {preview && (
        <div className="preview">
          <MockNotice source={preview.source} />
          <h2>Server</h2>
          <p><code>{preview.server_info.name}</code> v{preview.server_info.version} · protocol {preview.protocol_version}</p>
          <h2>Capabilities</h2>
          <Json label="capabilities" value={preview.capabilities} />
          <h2>Tool <span className="muted">({preview.tools.length})</span></h2>
          <ul className="tools">
            {preview.tools.map((t) => (
              <li key={t.name}>
                <code className="tool-name">{t.name}</code>
                <p>{t.description}</p>
                <Json label="inputSchema" value={t.input_schema} />
              </li>
            ))}
          </ul>
          <p className="muted">실제 등록 · 게시는 아직 지원하지 않습니다.</p>
        </div>
      )}
    </section>
  )
}
