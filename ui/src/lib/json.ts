/** Shown when `parseJson` keeps a large integer as text. */
export const KEPT_AS_TEXT =
  'Integers outside the JavaScript safe-integer range are sent as text, because a number would round them'

/**
 * Parse JSON, but keep each integer outside the safe-integer range
 * that a JavaScript number cannot hold exactly as its text, and call
 * `onKept` for it. This includes integers written with a decimal point
 * or an exponent, such as `9007199254740993e0`. An integer that a
 * number holds exactly, such as `9007199254740992`, stays a number. A
 * browser without `context.source` keeps the rounded number.
 */
export function parseJson(text: string, onKept: () => void): unknown {
  return JSON.parse(
    text,
    (_key, value: unknown, context?: { source?: string }) => {
      if (
        typeof value !== 'number' ||
        !Number.isInteger(value) ||
        Number.isSafeInteger(value) ||
        context?.source === undefined
      )
        return value
      const exact = exactInteger(context.source)
      if (exact === null || exact === BigInt(value)) return value
      onKept()
      return String(exact)
    },
  )
}

/** The exact integer a JSON number token names, or `null` if fractional. */
function exactInteger(source: string): bigint | null {
  const match = /^(-?)(\d+)(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(source)
  if (!match) return null
  const [, sign, whole, fraction = '', exponent = '0'] = match
  let digits = whole + fraction
  const shift = Number(exponent) - fraction.length
  if (shift < 0) {
    if (/[^0]/.test(digits.slice(shift))) return null
    digits = digits.slice(0, shift) || '0'
  } else {
    digits += '0'.repeat(shift)
  }
  return BigInt(sign + digits)
}
