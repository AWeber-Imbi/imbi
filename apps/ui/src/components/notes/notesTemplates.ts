import {
  AlertTriangle,
  BookOpen,
  FileText,
  Map,
  ShieldCheck,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'
import type { TagRef } from '@/types'

/**
 * Note templates surfaced from the empty-state grid. Each template seeds the
 * compose view with a starter tag so the template choice carries through to
 * the new-note form.
 */
export interface NoteTemplate {
  slug: string
  label: string
  hint: string
  icon: LucideIcon
  tag: TagRef
}

export const NOTE_TEMPLATES: NoteTemplate[] = [
  {
    slug: 'adr',
    label: 'ADR',
    hint: 'Context · Decision · Trade-offs',
    icon: FileText,
    tag: { name: 'ADR', slug: 'adr' },
  },
  {
    slug: 'security',
    label: 'Security review',
    hint: 'Findings · Follow-ups',
    icon: ShieldCheck,
    tag: { name: 'Security', slug: 'security' },
  },
  {
    slug: 'incident',
    label: 'Incident',
    hint: 'Timeline · Root cause · Actions',
    icon: AlertTriangle,
    tag: { name: 'Incident', slug: 'incident' },
  },
  {
    slug: 'roadmap',
    label: 'Roadmap',
    hint: 'Proposal · Milestones',
    icon: Map,
    tag: { name: 'Roadmap', slug: 'roadmap' },
  },
  {
    slug: 'pattern',
    label: 'Pattern',
    hint: 'When to reach for this',
    icon: Sparkles,
    tag: { name: 'Pattern', slug: 'pattern' },
  },
  {
    slug: 'runbook',
    label: 'Runbook',
    hint: 'Steps · Verification',
    icon: BookOpen,
    tag: { name: 'Runbook', slug: 'runbook' },
  },
]

export function findTemplate(slug: string | undefined): NoteTemplate | null {
  if (!slug) return null
  return NOTE_TEMPLATES.find((t) => t.slug === slug) ?? null
}
