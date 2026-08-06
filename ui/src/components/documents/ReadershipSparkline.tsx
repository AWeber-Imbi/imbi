import { useState } from 'react'

import type { DocumentTrendPoint } from '@/types'

interface Props {
  /** Ascending by day, as the analytics endpoint returns it. */
  trend: DocumentTrendPoint[]
}

const WIDTH = 340
const HEIGHT = 72
const TOP = 6
const BOTTOM = 66

/**
 * Views per day for one document.
 *
 * A single series, so it carries no legend — the caption underneath
 * names it and the date range it covers. Hovering a day pins that day's
 * numbers into the caption rather than floating a tooltip: the chart
 * lives inside a 396px popover, where a tooltip has nowhere to go.
 */
export function ReadershipSparkline({ trend }: Props) {
  const [hover, setHover] = useState<null | number>(null)

  if (trend.length === 0) return null

  const peak = Math.max(1, ...trend.map((point) => point.views))
  const step = trend.length > 1 ? WIDTH / (trend.length - 1) : 0
  const x = (index: number) => (trend.length > 1 ? index * step : WIDTH / 2)
  const y = (views: number) => BOTTOM - (views / peak) * (BOTTOM - TOP)

  const line = trend
    .map(
      (point, index) =>
        `${index === 0 ? 'M' : 'L'}${x(index)} ${y(point.views)}`,
    )
    .join(' ')
  const area = `${line} L${x(trend.length - 1)} ${BOTTOM} L${x(0)} ${BOTTOM} Z`
  const hitWidth = Math.max(step, 4)

  return (
    <div>
      <svg
        aria-label="Views per day"
        className="mt-3 block h-[72px] w-full"
        onMouseLeave={() => setHover(null)}
        role="img"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      >
        {[TOP, (TOP + BOTTOM) / 2, BOTTOM].map((rule) => (
          <line
            key={rule}
            stroke="var(--ds-border-tertiary)"
            strokeWidth={1}
            x1={0}
            x2={WIDTH}
            y1={rule}
            y2={rule}
          />
        ))}
        <path d={area} fill="var(--ds-action-bg)" opacity={0.1} />
        <path
          d={line}
          fill="none"
          stroke="var(--ds-action-bg)"
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
        />
        {hover != null && <Crosshair x={x(hover)} y={y(trend[hover].views)} />}
        {trend.map((point, index) => (
          <rect
            fill="transparent"
            height={HEIGHT}
            key={point.day}
            onMouseEnter={() => setHover(index)}
            width={hitWidth}
            x={x(index) - hitWidth / 2}
            y={0}
          />
        ))}
      </svg>
      <Caption point={hover == null ? null : trend[hover]} trend={trend} />
    </div>
  )
}

function Caption({
  point,
  trend,
}: {
  point: DocumentTrendPoint | null
  trend: DocumentTrendPoint[]
}) {
  return (
    <div className="text-tertiary mt-1.5 text-[11.5px]">
      {point ? (
        <>
          <span className="text-secondary">{formatDay(point.day)}</span> ·{' '}
          <span className="text-secondary tabular-nums">{point.views}</span>{' '}
          {plural(point.views, 'view')} ·{' '}
          <span className="text-secondary tabular-nums">{point.readers}</span>{' '}
          {plural(point.readers, 'reader')}
        </>
      ) : (
        <>
          {formatDay(trend[0].day)} to {formatDay(trend[trend.length - 1].day)}
        </>
      )}
    </div>
  )
}

function Crosshair({ x, y }: { x: number; y: number }) {
  return (
    <>
      <line
        stroke="var(--ds-border-secondary)"
        strokeWidth={1}
        x1={x}
        x2={x}
        y1={TOP}
        y2={BOTTOM}
      />
      <circle
        cx={x}
        cy={y}
        fill="var(--ds-action-bg)"
        r={3.5}
        stroke="var(--ds-bg-primary)"
        strokeWidth={2}
      />
    </>
  )
}

function formatDay(day: string): string {
  const parsed = new Date(`${day}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) return day
  return parsed.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
    year: 'numeric',
  })
}

function plural(count: number, noun: string): string {
  return count === 1 ? noun : `${noun}s`
}
