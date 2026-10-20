import { useState } from 'react'

import { Link } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Plus, X } from 'lucide-react'
import { toast } from 'sonner'

import {
  createSecretGrant,
  listSecretBindings,
  listSecretGrants,
} from '@/api/endpoints'
import { GitHubAppBindingSelect } from '@/components/admin/secrets/GitHubAppBindingSelect'
import { SecretDialog } from '@/components/admin/secrets/SecretDialog'
import type {
  SecretBinding,
  SecretGrantCreate,
} from '@/components/admin/secrets/types'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'

import {
  type AccessRow,
  accessRows,
  agentGrants,
  covers,
  GITHUB_PURPOSES,
  grantFor,
} from './access'
import type { SettingsDraft } from './agentDraft'
import { Field } from './OverviewTab'

interface AccessTabProps {
  agent: null | { id: string; name: string }
  errors: Record<string, string>
  onChange: (settings: SettingsDraft) => void
  orgSlug: string
  value: SettingsDraft
}

/**
 * What the agent can reach through the secrets broker: its GitHub App,
 * and the secrets that a grant gives it. A grant names the agent, so a
 * new agent gets grants after its first save. Grants apply at once;
 * they are not part of the agent version.
 */
export function AccessTab({
  agent,
  errors,
  onChange,
  orgSlug,
  value,
}: AccessTabProps) {
  const canReadGrants = useHasPermission('secret_grant:read')
  const canReadBindings = useHasPermission('secret_binding:read')
  const canRead = canReadGrants && canReadBindings
  const canWrite = useHasPermission('secret_grant:write')
  const queryClient = useQueryClient()
  const grants = useQuery({
    enabled: canRead,
    queryFn: ({ signal }) => listSecretGrants(orgSlug, signal),
    queryKey: ['secret-grants', orgSlug],
  })
  const bindings = useQuery({
    enabled: canRead,
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey: ['secret-bindings', orgSlug],
  })
  const create = useMutation({
    mutationFn: (body: SecretGrantCreate) => createSecretGrant(orgSlug, body),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: () => {
      toast.success('Access granted')
      void queryClient.invalidateQueries({
        queryKey: ['secret-grants', orgSlug],
      })
    },
  })

  const mine = agent ? agentGrants(grants.data ?? [], agent.id) : []
  const github = (bindings.data ?? []).find(
    (b) => b.reference === value.githubAppBinding,
  )
  const rows = accessRows(mine, bindings.data ?? [], github?.id ?? null)
  const grant = (binding: SecretBinding, purpose: string, mode: string) =>
    agent &&
    create.mutate(
      grantFor(
        agent,
        binding,
        purpose,
        mode as SecretGrantCreate['delivery_modes'][number],
      ),
    )

  return (
    <div className="flex flex-col gap-8">
      {(grants.error || bindings.error) && (
        <ErrorBanner
          error={grants.error ?? bindings.error}
          title="Failed to load the secret grants"
        />
      )}
      <p className="text-tertiary text-sm">
        The secrets broker gives the agent a secret only when a grant names the
        agent. Grants apply at once and are not part of the agent version.
        {!agent && ' Save the agent first to give it access.'}
        {!canRead &&
          ' You need secret_grant:read and secret_binding:read to see its grants.'}
      </p>

      <section className="flex flex-col gap-3">
        <div className="text-overline text-tertiary uppercase">GitHub App</div>
        <Field
          error={errors.githubAppBinding}
          help="An enabled github_app binding: the agent's own GitHub App. Saved with the agent."
          htmlFor="agent-github-app"
          label="Binding"
        >
          <GitHubAppBindingSelect
            id="agent-github-app"
            onChange={(reference) =>
              onChange({ ...value, githubAppBinding: reference ?? '' })
            }
            orgSlug={orgSlug}
            value={value.githubAppBinding || null}
          />
        </Field>
        {github && agent && canRead && (
          <ul className="border-tertiary divide-tertiary divide-y rounded-lg border">
            {GITHUB_PURPOSES.map(({ label, mode, purpose }) => {
              const ok = covers(mine, github.id, purpose, mode)
              return (
                <li className="flex items-center gap-3 px-3 py-2" key={purpose}>
                  {ok ? (
                    <Check className="text-success size-4" />
                  ) : (
                    <X className="text-tertiary size-4" />
                  )}
                  <span className="flex-1 text-sm">{label}</span>
                  <span className="text-tertiary font-mono text-xs">
                    {purpose}
                  </span>
                  {!ok && canWrite && (
                    <Button
                      disabled={create.isPending}
                      onClick={() => grant(github, purpose, mode)}
                      size="sm"
                      variant="outline"
                    >
                      Grant
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {agent && canRead && (
        <AgentSecrets
          agent={agent}
          bindings={(bindings.data ?? []).filter(
            (b) => b.enabled && b.id !== github?.id,
          )}
          canWrite={canWrite}
          error={create.error}
          isPending={create.isPending}
          onGrant={(body, done) => create.mutate(body, { onSuccess: done })}
          rows={rows}
        />
      )}
    </div>
  )
}

function AgentSecrets({
  agent,
  bindings,
  canWrite,
  error,
  isPending,
  onGrant,
  rows,
}: {
  agent: { id: string; name: string }
  bindings: SecretBinding[]
  canWrite: boolean
  error: unknown
  isPending: boolean
  onGrant: (body: SecretGrantCreate, done: () => void) => void
  rows: AccessRow[]
}) {
  const [adding, setAdding] = useState(false)
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <div className="text-overline text-tertiary flex-1 uppercase">
          Secrets
        </div>
        {canWrite && (
          <Button onClick={() => setAdding(true)} size="sm" variant="outline">
            <Plus className="size-4" />
            Add access
          </Button>
        )}
      </div>
      <p className="text-tertiary text-xs">
        The agent can request these with run_with_secret: each one goes into the
        environment of one command. Change or remove a grant in{' '}
        <Link className="text-action hover:underline" to="/admin/secrets">
          Admin › Secrets
        </Link>
        .
      </p>
      {rows.length === 0 ? (
        <p className="text-tertiary text-sm">No grant names this agent.</p>
      ) : (
        <table className="w-full text-sm">
          <thead className="text-tertiary text-left text-xs">
            <tr>
              <th className="py-1 font-normal">Reference</th>
              <th className="py-1 font-normal">Purposes</th>
              <th className="py-1 font-normal">Delivery</th>
              <th className="py-1 font-normal">TTL</th>
            </tr>
          </thead>
          <tbody className="divide-tertiary divide-y">
            {rows.map(({ binding, grant }) => (
              <tr key={`${grant.id}-${binding.id}`}>
                <td className="py-2 font-mono text-xs">
                  {binding.reference}
                  {grant.agent_ids.length > 1 && (
                    <span className="text-tertiary ml-2 font-sans">
                      shared with {grant.agent_ids.length - 1} other
                      {grant.agent_ids.length > 2 ? ' agents' : ' agent'}
                    </span>
                  )}
                </td>
                <td className="py-2 font-mono text-xs">
                  {grant.purposes.join(', ')}
                </td>
                <td className="py-2 font-mono text-xs">
                  {grant.delivery_modes.join(', ')}
                </td>
                <td className="py-2 font-mono text-xs">
                  {grant.max_ttl_seconds}s
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {adding && (
        <SecretDialog
          description={`A grant for ${agent.name} alone. The secret goes into the environment of one command at a time.`}
          error={error}
          fields={[
            {
              kind: 'select',
              label: 'Secret',
              name: 'binding',
              options: bindings.map((b) => ({
                label: b.reference,
                value: b.id,
              })),
              required: true,
            },
            {
              description: 'What the agent uses it for, e.g. npm or sentry',
              kind: 'text',
              label: 'Purpose',
              name: 'purpose',
              required: true,
            },
          ]}
          isPending={isPending}
          onClose={() => setAdding(false)}
          onSubmit={(values) => {
            const binding = bindings.find((b) => b.id === values.binding)
            if (!binding) return
            onGrant(
              grantFor(agent, binding, String(values.purpose), 'environment'),
              () => setAdding(false),
            )
          }}
          title="Add access"
        />
      )}
    </section>
  )
}
