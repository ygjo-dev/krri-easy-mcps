export default function MockNotice({ source }: { source: string }) {
  if (source !== 'mock') return null
  return <p className="notice">예시(mock) 데이터입니다. 실제 Gateway 연결 전입니다.</p>
}
