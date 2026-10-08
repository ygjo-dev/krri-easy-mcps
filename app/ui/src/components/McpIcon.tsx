// MCP 고유 로고가 없으므로 모노그램 하나로 통일한다. 색은 mcp_id 로 정해져 늘 같다.
const KNOWN: Record<string, string> = {
  'krri-map-location': 'MAP',
  'krri-railway-network': 'RAIL',
  'krri-admin-boundary': '행정',
  'krri-vworld-representative-data': 'VW',
  'krri-population-statistics': '인구',
  'krri-road-cctv': 'CCTV',
  'krri-ev-chargers': 'EV',
  'krri-knowledge': 'DOC',
  'krri-bim-viewer': 'BIM',
  'krri-dem': 'DEM',
  'krri-assembly-pledges-2024': '국회',
  'krri-election-pledges-2026': '지선',
  'route-accessibility': 'R5',
  'web-research': 'WEB',
  'gtfs-accessibility-aro': 'GTFS',
  'gtfs-accessibility-university': 'GTFS',
  'nodelink-accessibility-vwl': 'NODE',
}
const TONES = ['#2f6fed', '#15803d', '#c2410c', '#7c3aed', '#0e7490', '#a16207']

function monogram(mcpId: string): string {
  return KNOWN[mcpId] ?? mcpId.replace(/^krri-/, '').split(/[-_.]/)[0].slice(0, 3).toUpperCase()
}

function tone(mcpId: string): string {
  let h = 0
  for (const ch of mcpId) h = (h * 31 + ch.charCodeAt(0)) >>> 0
  return TONES[h % TONES.length]
}

export default function McpIcon({ mcpId, size = 'md' }: { mcpId: string; size?: 'md' | 'lg' }) {
  const text = monogram(mcpId)
  return (
    <span
      className={`mcp-icon mcp-icon-${size}${text.length > 3 ? ' mcp-icon-long' : ''}`}
      style={{ background: tone(mcpId) }}
      aria-hidden="true"
    >
      {text}
    </span>
  )
}
