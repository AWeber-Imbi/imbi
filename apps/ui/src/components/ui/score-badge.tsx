interface ScoreBadgeProps {
  score?: null | number
  /** sm = compact table cell; md = card with ring; lg = detail sidebar; xl = prominent list cell */
  size?: 'lg' | 'md' | 'sm' | 'xl'
  /** circle: rounded-full (projects list); square: rounded-lg (project detail) */
  variant?: 'circle' | 'square'
}

// fallow-ignore-next-line complexity
export function ScoreBadge({
  score,
  size = 'sm',
  variant = 'circle',
}: ScoreBadgeProps) {
  const rounded = variant === 'circle' ? 'rounded-full' : 'rounded-lg'

  if (score == null || !Number.isFinite(score)) {
    const dims =
      size === 'xl'
        ? 'h-20 w-20 text-[1.5rem]'
        : size === 'lg'
          ? 'h-16 w-16 text-2xl'
          : size === 'md'
            ? 'h-12 w-12 text-sm'
            : 'h-10 w-10 text-sm'
    return (
      <div
        className={`border-tertiary text-tertiary flex shrink-0 items-center justify-center border-[0.25px] font-medium ${rounded} ${dims}`}
      >
        —
      </div>
    )
  }

  const display = Math.round(score)
  const { bg, border, ring, text } = scoreClasses(display)

  if (size === 'xl') {
    return (
      <div
        className={`flex size-20 shrink-0 items-center justify-center border-[0.25px] text-[1.5rem] font-medium ${rounded} ${bg} ${border} ${text}`}
      >
        {display}
      </div>
    )
  }

  if (size === 'lg') {
    return (
      <div
        className={`flex size-16 shrink-0 items-center justify-center border-[0.25px] text-2xl font-medium ${rounded} ${bg} ${border} ${text}`}
      >
        {display}
      </div>
    )
  }

  if (size === 'md') {
    return (
      <div
        className={`flex size-12 shrink-0 items-center justify-center ring-2 ${rounded} ${bg} ${text} ${ring}`}
      >
        <span className="text-sm font-semibold">{display}</span>
      </div>
    )
  }

  return (
    <div
      className={`inline-flex size-10 items-center justify-center border ${rounded} ${bg} ${border} ${text}`}
    >
      <span className="text-sm font-semibold">{display}</span>
    </div>
  )
}

function scoreClasses(score: number): {
  bg: string
  border: string
  ring: string
  text: string
} {
  if (score >= 80)
    return {
      bg: 'bg-success',
      border: 'border-success',
      ring: 'ring-success',
      text: 'text-success',
    }
  if (score >= 70)
    return {
      bg: 'bg-warning',
      border: 'border-warning',
      ring: 'ring-warning',
      text: 'text-warning',
    }
  return {
    bg: 'bg-danger',
    border: 'border-danger',
    ring: 'ring-danger',
    text: 'text-danger',
  }
}
