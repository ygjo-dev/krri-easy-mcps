// MCP 고유 로고가 없으므로 모노그램 하나로 통일한다. 색은 server_id 로 정해져 늘 같다.
const KNOWN: Record<string, string> = {
  'asap-mcp-core': 'ASAP',
  'otp-router': 'OTP',
  'r5-server': 'R5',
  'web-search': 'WEB',
}
const TONES = ['#2f6fed', '#15803d', '#c2410c', '#7c3aed', '#0e7490', '#a16207']

function monogram(serverId: string): string {
  return KNOWN[serverId] ?? serverId.split(/[-_.]/)[0].slice(0, 3).toUpperCase()
}

function tone(serverId: string): string {
  let h = 0
  for (const ch of serverId) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return TONES[h % TONES.length]
}

export default function McpIcon({ serverId, size = 'md' }: { serverId: string; size?: 'md' | 'lg' }) {
  const text = monogram(serverId)
  return (
    <span
      className={`mcp-icon mcp-icon-${size}${text.length > 3 ? ' mcp-icon-long' : ''}`}
      style={{ background: tone(serverId) }}
      aria-hidden="true"
    >
      {text}
    </span>
  )
}
