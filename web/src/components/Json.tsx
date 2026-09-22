export default function Json({ label, value }: { label: string; value: unknown }) {
  return (
    <details>
      <summary>{label}</summary>
      {value === null || value === undefined ? (
        <p className="muted">제공되지 않음</p>
      ) : (
        <pre>{JSON.stringify(value, null, 2)}</pre>
      )}
    </details>
  )
}
