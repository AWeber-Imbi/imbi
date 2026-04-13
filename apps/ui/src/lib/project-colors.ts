export const TYPE_COLORS = [
  '#2563EB',
  '#DC2626',
  '#16A34A',
  '#D97706',
  '#7C3AED',
  '#0891B2',
  '#DB2777',
  '#65A30D',
]

export function getTypeColor(typeSlug: string): string {
  let hash = 0
  for (let i = 0; i < typeSlug.length; i++) {
    hash = (hash * 31 + typeSlug.charCodeAt(i)) | 0
  }
  return TYPE_COLORS[Math.abs(hash) % TYPE_COLORS.length]
}
