export type DetectedFormat = 'json' | 'unknown' | 'yaml'

// fallow-ignore-next-line complexity
export function detectFormat(input: string): DetectedFormat {
  const trimmed = input.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json'
  if (
    trimmed.includes(': ') ||
    trimmed.includes(':\n') ||
    trimmed.startsWith('---')
  )
    return 'yaml'
  return 'unknown'
}
