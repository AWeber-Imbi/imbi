/**
 * Threshold-based color and icon resolution for x-ui blueprint properties.
 *
 * Supports three map types:
 *   - color-map / icon-map:   exact value lookup (existing)
 *   - color-range / icon-range: numeric threshold  (e.g. ">=90": "green")
 *   - color-age / icon-age:   duration-since threshold on dates (e.g. ">30d": "red")
 *
 * Threshold keys use operator prefixes: >=, >, <=, <, ==
 * Age values use duration suffixes: s (seconds), m (minutes), h (hours), d (days), w (weeks)
 */

interface ThresholdEntry {
  op: '<' | '<=' | '==' | '>' | '>='
  result: string
  threshold: number
}

type ThresholdMap = Record<string, string>

const OP_REGEX = /^(>=|>|<=|<|==)\s*(.+)$/

const DURATION_UNITS: Record<string, number> = {
  d: 86400,
  h: 3600,
  m: 60,
  s: 1,
  w: 604800,
}

const DURATION_REGEX = /^(\d+(?:\.\d+)?)\s*([smhdw])$/

export interface XUiMaps {
  colorAge?: ThresholdMap
  colorMap?: ThresholdMap
  colorRange?: ThresholdMap
  iconAge?: ThresholdMap
  iconMap?: ThresholdMap
  iconRange?: ThresholdMap
}

/**
 * Resolve color from all x-ui map types. Priority: exact map → range → age.
 */
export function resolveColor(
  maps: XUiMaps,
  rawValue: unknown,
): string | undefined {
  const rawStr = rawValue != null ? String(rawValue) : null

  if (maps.colorMap && rawStr != null) {
    const exact = caseInsensitiveLookup(maps.colorMap, rawStr)
    if (exact) return exact
  }
  if (maps.colorRange) {
    const rangeResult = resolveRange(maps.colorRange, rawValue)
    if (rangeResult) return rangeResult
  }
  if (maps.colorAge) {
    const ageResult = resolveAge(maps.colorAge, rawValue)
    if (ageResult) return ageResult
  }
  return undefined
}

/**
 * Resolve icon from all x-ui map types. Priority: exact map → range → age.
 */
export function resolveIcon(
  maps: XUiMaps,
  rawValue: unknown,
): string | undefined {
  const rawStr = rawValue != null ? String(rawValue) : null

  if (maps.iconMap && rawStr != null) {
    const exact = caseInsensitiveLookup(maps.iconMap, rawStr)
    if (exact) return exact
  }
  if (maps.iconRange) {
    const rangeResult = resolveRange(maps.iconRange, rawValue)
    if (rangeResult) return rangeResult
  }
  if (maps.iconAge) {
    const ageResult = resolveAge(maps.iconAge, rawValue)
    if (ageResult) return ageResult
  }
  return undefined
}

/** Case-insensitive lookup in a string-keyed record. */
function caseInsensitiveLookup(
  map: Record<string, string>,
  key: string,
): string | undefined {
  if (map[key] !== undefined) return map[key]
  const lower = key.toLowerCase()
  for (const k of Object.keys(map)) {
    if (k.toLowerCase() === lower) return map[k]
  }
  return undefined
}

function evaluateThreshold(
  entries: ThresholdEntry[],
  value: number,
): string | undefined {
  for (const { op, result, threshold } of entries) {
    let matches = false
    switch (op) {
      case '<':
        matches = value < threshold
        break
      case '<=':
        matches = value <= threshold
        break
      case '==':
        matches = value === threshold
        break
      case '>':
        matches = value > threshold
        break
      case '>=':
        matches = value >= threshold
        break
    }
    if (matches) return result
  }
  return undefined
}

function parseDuration(value: string): null | number {
  const match = value.match(DURATION_REGEX)
  if (!match) return null
  const amount = parseFloat(match[1])
  const unit = DURATION_UNITS[match[2]]
  return amount * unit
}

function parseThresholds(
  map: ThresholdMap,
  parseFn: (v: string) => null | number,
): ThresholdEntry[] {
  const entries: ThresholdEntry[] = []
  for (const [key, result] of Object.entries(map)) {
    const match = key.match(OP_REGEX)
    if (!match) continue
    const op = match[1] as ThresholdEntry['op']
    const threshold = parseFn(match[2].trim())
    if (threshold === null) continue
    entries.push({ op, result, threshold })
  }
  return entries
}

/**
 * Evaluate a color-age or icon-age map against a date/datetime value.
 * Keys are operator-prefixed durations: ">30d", "<=7d", ">2h"
 * The elapsed seconds since the date value is compared to the threshold.
 * Evaluated in document order; first match wins.
 */
function resolveAge(map: ThresholdMap, rawValue: unknown): string | undefined {
  if (rawValue == null) return undefined
  const date = new Date(String(rawValue))
  if (isNaN(date.getTime())) return undefined
  const elapsedSeconds = (Date.now() - date.getTime()) / 1000
  const entries = parseThresholds(map, parseDuration)
  return evaluateThreshold(entries, elapsedSeconds)
}

/**
 * Evaluate a color-range or icon-range map against a numeric value.
 * Keys are operator-prefixed numbers: ">=90", "<70", "==0"
 * Evaluated in document order; first match wins.
 */
function resolveRange(
  map: ThresholdMap,
  rawValue: unknown,
): string | undefined {
  const num =
    typeof rawValue === 'number' ? rawValue : parseFloat(String(rawValue))
  if (isNaN(num)) return undefined
  const entries = parseThresholds(map, (v) => {
    const n = parseFloat(v)
    return isNaN(n) ? null : n
  })
  return evaluateThreshold(entries, num)
}
