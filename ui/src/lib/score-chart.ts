// Compute the score-history chart's y-axis floor, ceiling, and tick marks from
// the visible scores. The top is always 100. The floor is normally 50 —
// preserving the established 50–100 view for healthy projects — but drops in
// steps of 10 (down to 0) when a score falls below 50. Previously yMin was
// hardcoded to 50, so sub-50 scores were plotted below the chart floor (off the
// bottom, past the x-axis labels) and the area fill inverted where the line
// crossed the y=50 baseline. Ticks span [yMin, 100] in increments of 10.
export function computeScoreYAxis(scores: number[]): {
  ticks: number[]
  yMax: number
  yMin: number
} {
  const yMax = 100
  const dataMin = scores.length > 0 ? Math.min(...scores) : yMax
  const yMin = Math.max(0, Math.min(50, Math.floor(dataMin / 10) * 10))
  const ticks: number[] = []
  for (let t = yMin; t <= yMax; t += 10) ticks.push(t)
  return { ticks, yMax, yMin }
}
