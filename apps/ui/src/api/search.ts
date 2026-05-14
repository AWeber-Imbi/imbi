export type { SearchResult } from './endpoints'
export { searchOrganization as searchOrg } from './endpoints'

export type ConfidenceLabel = 'Close' | 'Related' | 'Strong'

/** Convert cosine distance (0=identical, 2=opposite) to a confidence label. */
export function getConfidenceLabel(distance: number): ConfidenceLabel | null {
  const similarity = 1 - distance
  if (similarity >= 0.7) return 'Strong'
  if (similarity >= 0.45) return 'Close'
  if (similarity >= 0.25) return 'Related'
  return null
}
