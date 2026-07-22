import { LABEL_SWATCHES, swatchForType } from '@/lib/chip-colors'

/** Pick a label palette hex for a blueprint type. Relationship is pinned to Honey. */
export function getTypeSwatch(type: string, allTypes: string[]): string {
  if (type === 'relationship') {
    return (
      LABEL_SWATCHES.find((s) => s.name === 'Honey')?.hex ??
      LABEL_SWATCHES[2].hex
    )
  }
  return swatchForType(type, allTypes)
}
