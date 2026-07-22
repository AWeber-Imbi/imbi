export function DiffBar({
  additions,
  deletions,
}: {
  additions: number
  deletions: number
}) {
  const total = additions + deletions
  if (total === 0) return <span className="text-tertiary text-xs">—</span>
  const addBlocks = Math.round((additions / total) * 5)
  const delBlocks = 5 - addBlocks
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="text-xs">
        <span className="text-success">+{additions.toLocaleString()}</span>
        <span className="text-tertiary"> · </span>
        <span className="text-danger">-{deletions.toLocaleString()}</span>
      </div>
      <div className="flex gap-0.5">
        {Array.from({ length: addBlocks }).map((_, i) => (
          <div
            className="h-2 w-3.5"
            key={`a${i}`}
            style={{ backgroundColor: 'var(--text-color-success)' }}
          />
        ))}
        {Array.from({ length: delBlocks }).map((_, i) => (
          <div
            className="h-2 w-3.5"
            key={`d${i}`}
            style={{ backgroundColor: 'var(--text-color-danger)' }}
          />
        ))}
      </div>
    </div>
  )
}
