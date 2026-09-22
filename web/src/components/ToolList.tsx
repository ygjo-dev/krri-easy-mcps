import type { Tool } from '../types/api'

export default function ToolList({ tools }: { tools: Tool[] }) {
  return (
    <ul className="tools">
      {tools.map((t) => (
        <li key={t.name}>
          <code className="tool-name">{t.name}</code>
          <p>{t.description}</p>
          {t.parameters.length === 0 ? (
            <p className="muted">parameter 없음</p>
          ) : (
            <table>
              <thead>
                <tr><th>parameter</th><th>type</th><th>필수</th><th>설명</th></tr>
              </thead>
              <tbody>
                {t.parameters.map((p) => (
                  <tr key={p.name}>
                    <td><code>{p.name}</code></td>
                    <td>{p.type}{p.enum ? ` (${p.enum.join(' | ')})` : ''}</td>
                    <td>{p.required ? '예' : ''}</td>
                    <td>
                      {p.description}
                      {p.default !== null && p.default !== undefined ? ` (기본 ${JSON.stringify(p.default)})` : ''}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </li>
      ))}
    </ul>
  )
}
