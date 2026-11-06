/**
 * How a project is delivered: the per-project ``delivery_mode`` setting
 * resolved against the ``deployable`` / ``releasable`` flags of its
 * project types. Mirrors ``imbi.common.models.resolve_delivery`` so the
 * tabs, the projects list, and the API agree on what a project ships.
 */

/**
 * The resolved delivery flags of one project. Both false covers an
 * explicit `disabled` and a project whose types carry neither flag;
 * both true only happens under `project-type` on a project carrying one
 * type of each kind, which the tabs treat as deployable.
 */
export interface Delivery {
  deployable: boolean
  releasable: boolean
}

export type DeliveryMode =
  | 'deployable'
  | 'disabled'
  | 'project-type'
  | 'releasable'

export interface DeliveryModeOption {
  description: string
  label: string
  value: DeliveryMode
}

export const DEFAULT_DELIVERY_MODE: DeliveryMode = 'project-type'

export const DELIVERY_MODE_OPTIONS: readonly DeliveryModeOption[] = [
  {
    description:
      'Follow the deployable or releasable flag of the project types.',
    label: 'By project type',
    value: 'project-type',
  },
  {
    description: 'Deploy into environments and promote between them.',
    label: 'Deployable',
    value: 'deployable',
  },
  {
    description: 'Cut tags and releases with no deploy step.',
    label: 'Releasable',
    value: 'releasable',
  },
  {
    description:
      'Releases are managed outside Imbi. Hides the Deployments and ' +
      'Releases tabs and refuses deploys, promotes, and release cuts.',
    label: 'Disabled',
    value: 'disabled',
  },
]

export interface DeliveryProject {
  delivery_mode?: DeliveryMode | null | string
  project_types?: null | object[]
}

/**
 * Resolve what, if anything, Imbi does to ship `project`.
 *
 * An explicit `deployable` / `releasable` mode replaces the type flags
 * and `disabled` clears them. `project-type` (and a missing or unknown
 * value, from a project written before the setting existed) passes the
 * types through: a flag is set when any type carries it.
 */
export function resolveDelivery(project: DeliveryProject): Delivery {
  const mode = project.delivery_mode
  if (mode === 'disabled') return { deployable: false, releasable: false }
  if (mode === 'deployable') return { deployable: true, releasable: false }
  if (mode === 'releasable') return { deployable: false, releasable: true }
  const types = project.project_types ?? []
  return {
    deployable: types.some(
      (pt) => (pt as { deployable?: boolean }).deployable === true,
    ),
    releasable: types.some(
      (pt) => (pt as { releasable?: boolean }).releasable === true,
    ),
  }
}
