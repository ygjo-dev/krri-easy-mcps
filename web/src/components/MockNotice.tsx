export default function MockNotice({ source }: { source: string }) {
  if (source !== 'mock') return null
  return <p className="notice">mock 데이터입니다. 실제 Gateway / agentic_ai 연결 전입니다.</p>
}
