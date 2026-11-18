/** Shown when `parseJson` keeps a large integer as text. */
export const KEPT_AS_TEXT =
  'Large integers are sent as text, because a JavaScript number would change their value'

/**
 * Parse JSON, but keep each integer that a JavaScript number cannot
 * hold exactly as its text, and call `onKept` for it. A browser
 * without `context.source` keeps the rounded number.
 */
export function parseJson(text: string, onKept: () => void): unknown {
  return JSON.parse(
    text,
    (_key, value: unknown, context?: { source?: string }) => {
      const source = context?.source
      if (
        typeof value === 'number' &&
        !Number.isSafeInteger(value) &&
        source !== undefined &&
        /^-?\d+$/.test(source)
      ) {
        onKept()
        return source
      }
      return value
    },
  )
}
