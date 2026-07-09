// Plugin Architecture v3 — capability presentation metadata.
//
// The platform enumerates a fixed capability vocabulary. A plugin manifest
// supplies each capability's label/description/options; this table supplies
// the stable UI concerns (icon, canonical label fallback, surfaces, and
// whether it is project-scoped) so the list view can render enabled
// capabilities as icons without loading every manifest.

import {
  Gauge,
  GitBranch,
  GitCommitHorizontal,
  GitPullRequest,
  Key,
  type LucideIcon,
  Rocket,
  ScrollText,
  Siren,
  SlidersHorizontal,
  Webhook,
  Wrench,
} from 'lucide-react'

import type { CapabilityKind, CapabilitySurface } from '@/types'

export interface CapabilityMeta {
  icon: LucideIcon
  label: string
  // Project-scoped capabilities participate in per-project-type assignment.
  // Non-scoped ones (identity) apply org-wide.
  projectScoped: boolean
  surfaces: CapabilitySurface[]
}

// Fixed surface classification mirrors imbi_common CAPABILITY_SURFACES.
const CAPABILITY_META: Record<CapabilityKind, CapabilityMeta> = {
  analysis: {
    icon: Gauge,
    label: 'Project analysis',
    projectScoped: true,
    surfaces: ['ui', 'api'],
  },
  'commit-sync': {
    icon: GitCommitHorizontal,
    label: 'Commit history sync',
    projectScoped: true,
    surfaces: ['api', 'webhook'],
  },
  configuration: {
    icon: SlidersHorizontal,
    label: 'Configuration store',
    projectScoped: true,
    surfaces: ['ui', 'api'],
  },
  deployment: {
    icon: Rocket,
    label: 'Deployments',
    projectScoped: true,
    surfaces: ['ui', 'api'],
  },
  identity: {
    icon: Key,
    label: 'Sign-in / user identity',
    projectScoped: false,
    surfaces: ['api'],
  },
  incidents: {
    icon: Siren,
    label: 'Incidents',
    projectScoped: true,
    surfaces: ['ui', 'api'],
  },
  lifecycle: {
    icon: GitBranch,
    label: 'Repository lifecycle',
    projectScoped: true,
    surfaces: ['api'],
  },
  logs: {
    icon: ScrollText,
    label: 'Logs',
    projectScoped: true,
    surfaces: ['ui', 'api'],
  },
  'pr-sync': {
    icon: GitPullRequest,
    label: 'Pull request sync',
    projectScoped: true,
    surfaces: ['api', 'webhook'],
  },
  tools: {
    icon: Wrench,
    label: 'Agent tools',
    projectScoped: true,
    surfaces: ['tools'],
  },
  'webhook-actions': {
    icon: Webhook,
    label: 'Webhook actions',
    projectScoped: true,
    surfaces: ['webhook'],
  },
}

// Stable display order for capability lists.
const CAPABILITY_KINDS: CapabilityKind[] = [
  'deployment',
  'lifecycle',
  'configuration',
  'logs',
  'analysis',
  'incidents',
  'commit-sync',
  'pr-sync',
  'webhook-actions',
  'identity',
  'tools',
]

export function capabilityMeta(kind: string): CapabilityMeta | undefined {
  return CAPABILITY_META[kind as CapabilityKind]
}

// Order a set of capability kinds by the canonical display order, with any
// unknown kinds appended in their original order.
export function orderCapabilities(kinds: string[]): string[] {
  const rank = (k: string) => {
    const i = CAPABILITY_KINDS.indexOf(k as CapabilityKind)
    return i === -1 ? CAPABILITY_KINDS.length : i
  }
  return [...kinds].sort((a, b) => rank(a) - rank(b))
}
