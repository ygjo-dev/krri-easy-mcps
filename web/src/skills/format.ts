// Skills 화면의 작은 도우미. 날짜는 BFF 가 주는 unix 초 → 한국 시각.
export function formatDate(seconds: number): string {
  return new Intl.DateTimeFormat('ko-KR', { timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit' })
    .format(new Date(seconds * 1000))
    .replace(/\.\s?/g, '.')
    .replace(/\.$/, '')
}

export function formatDateTime(seconds: number): string {
  return new Intl.DateTimeFormat('ko-KR', {
    timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(seconds * 1000))
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

// frontmatter(--- … ---)를 떼어 낸 SKILL.md 본문
export function stripFrontmatter(text: string): string {
  const lines = text.split(/\r?\n/)
  if (lines[0]?.trim() !== '---') return text
  const end = lines.findIndex((line, i) => i > 0 && line.trim() === '---')
  return end < 0 ? text : lines.slice(end + 1).join('\n')
}

// 받은 ZIP 을 브라우저 다운로드로 넘긴다
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
