// 작은 inline SVG. 새 icon dependency 를 들이지 않는다.
export function WrenchIcon() {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path fill="currentColor" d="M14.7 3.6l-2.1 2.1-1.9-.4-.4-1.9 2.1-2.1A4 4 0 0 0 7.6 6.2L1.8 12a1.5 1.5 0 0 0 2.1 2.1l5.8-5.8a4 4 0 0 0 5-4.7z" />
    </svg>
  )
}

export function SearchIcon() {
  return (
    <svg className="icon" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      <path d="M11 11l3.5 3.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  )
}

export function ChevronIcon() {
  return (
    <svg className="icon chevron" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}
