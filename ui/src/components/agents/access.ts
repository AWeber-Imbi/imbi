import type {
  SecretBinding,
  SecretGrant,
  SecretGrantCreate,
} from '@/components/admin/secrets/types'

// The rules of the Access tab, without React: which grants apply to an
// agent, and the grant that gives it one GitHub App purpose.

type DeliveryMode = SecretGrantCreate['delivery_modes'][number]

/** What the agent's GitHub App binding is for, and how it is delivered. */
export const GITHUB_PURPOSES: {
  label: string
  mode: DeliveryMode
  purpose: string
}[] = [
  {
    label: 'Clone the project repositories',
    mode: 'file_descriptor',
    purpose: 'workspace_checkout',
  },
  {
    label: 'Push, and open pull requests and issues',
    mode: 'environment',
    purpose: 'github_write',
  },
  {
    label: 'Fetch plugins from private marketplaces',
    mode: 'file_descriptor',
    purpose: 'marketplace_fetch',
  },
]

export interface AccessRow {
  binding: SecretBinding
  grant: SecretGrant
}

/** One row for each binding of each grant, less the GitHub App binding. */
export function accessRows(
  grants: SecretGrant[],
  bindings: SecretBinding[],
  githubBindingId: null | string,
): AccessRow[] {
  const byId = new Map(bindings.map((b) => [b.id, b]))
  return grants.flatMap((grant) =>
    grant.binding_ids
      .filter((id) => id !== githubBindingId)
      .flatMap((id) => {
        const binding = byId.get(id)
        return binding ? [{ binding, grant }] : []
      }),
  )
}

/** The enabled grants that name the agent. The broker needs one. */
export function agentGrants(
  grants: SecretGrant[],
  agentId: string,
): SecretGrant[] {
  return grants.filter((g) => g.enabled && g.agent_ids.includes(agentId))
}

/** Whether a grant allows the binding for the purpose and mode. */
export function covers(
  grants: SecretGrant[],
  bindingId: string,
  purpose: string,
  mode: string,
): boolean {
  return grants.some(
    (g) =>
      g.binding_ids.includes(bindingId) &&
      g.purposes.includes(purpose) &&
      g.delivery_modes.includes(mode),
  )
}

/** A grant for one agent, one binding, one purpose, and one mode. */
export function grantFor(
  agent: { id: string; name: string },
  binding: SecretBinding,
  purpose: string,
  mode: DeliveryMode,
): SecretGrantCreate {
  return {
    agent_ids: [agent.id],
    binding_ids: [binding.id],
    delivery_modes: [mode],
    description: `${agent.name}: ${purpose} with ${binding.reference}`,
    enabled: true,
    max_ttl_seconds: Math.min(900, binding.max_ttl_seconds),
    project_ids: [],
    purposes: [purpose],
  }
}
