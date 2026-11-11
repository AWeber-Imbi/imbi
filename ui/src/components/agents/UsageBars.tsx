import { formatDay } from './agentUsage'

export interface UsageSeries {
  color: string
  key: string
  values: number[]
}

interface UsageBarsProps {
  days: string[]
  format: (value: number) => string
  height?: number
  /** The label of the chart, for screen readers. */
  label: string
  /** An optional line over the bars, with its own axis on the right. */
  line?: { color: string; values: number[] }
  /** Stacked, first series at the bottom. One value for each day. */
  series: UsageSeries[]
}

/**
 * Daily bars, stacked by series, as the design draws them: flex
 * columns, no chart library. The y axis has five ticks from zero.
 */
export function UsageBars({
  days,
  format,
  height = 200,
  label,
  line,
  series,
}: UsageBarsProps) {
  const totals = days.map((_, i) => series.reduce((n, s) => n + s.values[i], 0))
  const max = niceMax(Math.max(...totals))
  const lineMax = line ? niceMax(Math.max(...line.values), 1) : 0
  const ticks = [4, 3, 2, 1, 0]
  const tickEvery = Math.ceil(days.length / 8)
  const points = line?.values
    .map(
      (v, i) =>
        `${((i + 0.5) / days.length) * 100},${100 - (v / lineMax) * 100}`,
    )
    .join(' ')

  return (
    <div className="flex gap-3">
      <div
        className="flex w-16 shrink-0 flex-col justify-between text-right"
        style={{ height }}
      >
        {ticks.map((t) => (
          <span
            className="text-tertiary font-mono text-xs tabular-nums"
            key={t}
          >
            {format((max / 4) * t)}
          </span>
        ))}
      </div>
      <div className="min-w-0 flex-1">
        <div
          aria-label={label}
          className="relative"
          role="img"
          style={{ height }}
        >
          <div className="flex h-full items-end gap-1">
            {days.map((day, i) => (
              <div
                className="flex h-full flex-1 flex-col-reverse gap-px"
                key={day}
                title={`${formatDay(day)} · ${format(totals[i])}${line ? ` · ${line.values[i]} runs` : ''}`}
              >
                {series.map(
                  (s) =>
                    s.values[i] > 0 && (
                      <div
                        className="rounded-[1px]"
                        key={s.key}
                        style={{
                          background: s.color,
                          height: `${(s.values[i] / max) * 100}%`,
                        }}
                      />
                    ),
                )}
              </div>
            ))}
          </div>
          {line && (
            <svg
              className="pointer-events-none absolute inset-0 size-full overflow-visible"
              preserveAspectRatio="none"
              viewBox="0 0 100 100"
            >
              <polyline
                fill="none"
                points={points}
                stroke={line.color}
                strokeLinejoin="round"
                strokeWidth={1.5}
                vectorEffect="non-scaling-stroke"
              />
            </svg>
          )}
        </div>
        <div className="border-border mt-2 flex border-t pt-2">
          {days.map((day, i) => (
            <span
              className="text-tertiary flex-1 text-center font-mono text-xs whitespace-nowrap"
              key={day}
            >
              {i % tickEvery === 0 ? formatDay(day) : ''}
            </span>
          ))}
        </div>
      </div>
      {line && (
        <div
          className="flex w-10 shrink-0 flex-col justify-between"
          style={{ height }}
        >
          {ticks.map((t) => (
            <span
              className="font-mono text-xs tabular-nums"
              key={t}
              style={{ color: line.color }}
            >
              {(lineMax / 4) * t}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/** The top of an axis with four steps of 1, 2, or 5 times 10^n. */
function niceMax(peak: number, minStep = 0): number {
  const raw = Math.max(peak / 4, minStep)
  if (!(raw > 0)) return 4
  const p = 10 ** Math.floor(Math.log10(raw))
  const m = raw / p
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p * 4
}
