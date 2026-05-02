interface ScoreBadgeProps {
  score?: null | number
  /** sm = compact table cell; md = card with ring; lg = detail sidebar */
  size?: 'lg' | 'md' | 'sm'
  /** circle: rounded-full (projects list); square: rounded-lg (project detail) */
  variant?: 'circle' | 'square'
}

export function ScoreBadge({
  score,
  size = 'sm',
  variant = 'circle',
}: ScoreBadgeProps) {
  const rounded = variant === 'circle' ? 'rounded-full' : 'rounded-lg'

  if (score == null || !Number.isFinite(score)) {
    const dims =
      size === 'lg'
        ? 'h-16 w-16 text-2xl'
        : size === 'md'
          ? 'h-12 w-12 text-sm'
          : 'h-10 w-10 text-sm'
    return (
      <div
        className={`flex flex-shrink-0 items-center justify-center font-medium text-tertiary ${rounded} ${dims}`}
      >
        —
      </div>
    )
  }

  const display = Math.round(score)
  const { bg, ring, text } = scoreClasses(display)

  if (size === 'lg') {
    return (
      <div
        className={`flex h-16 w-16 flex-shrink-0 items-center justify-center text-2xl font-medium ${rounded} ${bg} ${text}`}
      >
        {display}
      </div>
    )
  }

  if (size === 'md') {
    return (
      <div
        className={`flex h-12 w-12 flex-shrink-0 items-center justify-center ring-4 ${rounded} ${bg} ${text} ${ring}`}
      >
        <span className="text-sm font-semibold">{display}</span>
      </div>
    )
  }

  return (
    <div
      className={`inline-flex h-10 w-10 items-center justify-center ${rounded} ${bg} ${text}`}
    >
      <span className="text-sm font-semibold">{display}</span>
    </div>
  )
}

function scoreClasses(score: number): {
  bg: string
  ring: string
  text: string
} {
  if (score >= 80)
    return {
      bg: 'bg-success',
      ring: 'ring-success',
      text: 'text-success',
    }
  if (score >= 70)
    return {
      bg: 'bg-warning',
      ring: 'ring-warning',
      text: 'text-warning',
    }
  return { bg: 'bg-danger', ring: 'ring-danger', text: 'text-danger' }
}
