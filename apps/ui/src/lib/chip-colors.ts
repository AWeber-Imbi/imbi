export interface ChipColors {
  bg: string
  border: string
  fg: string
}

export interface LabelSwatch {
  hex: string
  name: string
}

/** Canonical 8-swatch label palette used across the product for user-picked colors. */
export const LABEL_SWATCHES: LabelSwatch[] = [
  { hex: '#C86B5E', name: 'Clay' },
  { hex: '#D98847', name: 'Ember' },
  { hex: '#C9A227', name: 'Honey' },
  { hex: '#6B9A3F', name: 'Moss' },
  { hex: '#5A89C9', name: 'Dusk' },
  { hex: '#8C82D4', name: 'Lilac' },
  { hex: '#C96B97', name: 'Rose' },
  { hex: '#7A7873', name: 'Stone' },
]

export function darken(hex: string, amt: number): null | string {
  const rgb = hexToRgb(hex)
  if (!rgb) return null
  const r = Math.round(rgb.r * (1 - amt))
  const g = Math.round(rgb.g * (1 - amt))
  const b = Math.round(rgb.b * (1 - amt))
  return `rgb(${r},${g},${b})`
}

export function deriveChipColors(
  hex: string,
  isDarkMode: boolean,
): ChipColors | null {
  const rgb = hexToRgb(hex)
  if (!rgb) return null
  const fg = isDarkMode ? lighten(hex, 0.3) : darken(hex, 0.35)
  if (!fg) return null
  return {
    bg: `rgba(${rgb.r},${rgb.g},${rgb.b},0.2)`,
    border: `rgba(${rgb.r},${rgb.g},${rgb.b},0.4)`,
    fg,
  }
}

export function hexToRgb(
  hex: string,
): null | { b: number; g: number; r: number } {
  if (!/^#[0-9a-fA-F]{6}$/.test(hex)) return null
  const n = parseInt(hex.slice(1), 16)
  return { b: n & 255, g: (n >> 8) & 255, r: (n >> 16) & 255 }
}

export function lighten(hex: string, amt: number): null | string {
  const rgb = hexToRgb(hex)
  if (!rgb) return null
  const r = Math.round(rgb.r + (255 - rgb.r) * amt)
  const g = Math.round(rgb.g + (255 - rgb.g) * amt)
  const b = Math.round(rgb.b + (255 - rgb.b) * amt)
  return `rgb(${r},${g},${b})`
}

/** Deterministically pick a swatch hex for a type name given a full type list. */
export function swatchForType(type: string, allTypes: string[]): string {
  const idx = allTypes.indexOf(type)
  const safe = idx >= 0 ? idx : 0
  return LABEL_SWATCHES[safe % LABEL_SWATCHES.length].hex
}
