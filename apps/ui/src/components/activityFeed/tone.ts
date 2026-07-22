// Semantic tone → design-system classes/vars for activity status markers.
// Chip classes use the per-utility DS colors (bg-*/text-*); dot colors are
// saturated CSS vars that read on both themes without per-theme overrides.

export type Tone =
  | 'accent'
  | 'danger'
  | 'info'
  | 'neutral'
  | 'success'
  | 'warning'

export interface ToneStyle {
  /** Tailwind classes for a status chip background + text. */
  chip: string
  /** CSS value for a status dot background. */
  dotVar: string
}

const TONE_STYLES: Record<Tone, ToneStyle> = {
  accent: { chip: 'bg-accent text-accent', dotVar: 'var(--ds-text-accent)' },
  danger: { chip: 'bg-danger text-danger', dotVar: 'var(--ds-text-danger)' },
  info: { chip: 'bg-info text-info', dotVar: 'var(--color-activity-info-dot)' },
  neutral: {
    chip: 'bg-secondary text-tertiary',
    dotVar: 'var(--color-activity-neutral-dot)',
  },
  success: {
    chip: 'bg-success text-success',
    dotVar: 'var(--ds-text-success)',
  },
  warning: {
    chip: 'bg-warning text-warning',
    dotVar: 'var(--color-activity-warning-dot)',
  },
}

export function toneStyle(tone: Tone): ToneStyle {
  return TONE_STYLES[tone]
}
