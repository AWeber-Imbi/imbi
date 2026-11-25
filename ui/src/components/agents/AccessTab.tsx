import { useState } from 'react'

import { Link } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Check, Plus, X } from 'lucide-react'
import { toast } from 'sonner'

import { removeSecretGrantAgent } from '@/api/endpoints'
import { GitHubAppBindingSelect } from '@/components/admin/secrets/GitHubAppBindingSelect'
import { SecretDialog } from '@/components/admin/secrets/SecretDialog'
import {
  type SecretBinding,
  type SecretGrant,
  SETUP_PURPOSES,
} from '@/components/admin/secrets/types'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { extractApiErrorDetail } from '@/lib/apiError'

import {
  type AccessRow,
  accessRows,
  bindingOf,
  canSupplyRunner,
  coveringGrant,
  covers,
  fieldReferences,
  GITHUB_PURPOSES,
  purposeSuggestions,
} from './access'
import type { SettingsDraft } from './agentDraft'
import { agentsPath } from './agentsNav'
import { Field } from './OverviewTab'
import { type GrantAgent, useAgentGrant } from './useAgentGrant'

// The purpose of the runner's model key resolution.
const MODEL_PURPOSE = 'model_inference'

// Radix Select refuses an empty item value.
const ORG_KEY = '__organization__'

interface AccessTabProps {
  agent: GrantAgent | null
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
  const {
    bindings,
    canGrant,
    canRead,
    canWrite,
    ensure,
    grants,
    mayGrant,
    mine,
    save,
  } = useAgentGrant(orgSlug, agent)
  const queryClient = useQueryClient()
  const revoke = useMutation({
    mutationFn: (grant: SecretGrant) =>
      removeSecretGrantAgent(orgSlug, grant.id, agent!.id),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async () => {
      toast.success('Access removed')
      await queryClient.invalidateQueries({
        queryKey: ['secret-grants', orgSlug],
      })
    },
  })

  const github = (bindings.data ?? []).find(
    (b) => b.reference === value.githubAppBinding,
  )
  const rows = accessRows(mine, bindings.data ?? [], github?.id ?? null)

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
          <ul className="divide-tertiary border-tertiary divide-y rounded-lg border">
            {GITHUB_PURPOSES.map(({ label, mode, purpose }) => {
              const by = coveringGrant(mine, github.id, purpose, mode)
              const ok = by !== undefined
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
                  {!ok && canGrant(github) && (
                    <Button
                      disabled={save.isPending}
                      onClick={() => ensure(github, purpose, mode)}
                      size="sm"
                      variant="outline"
                    >
                      Grant
                    </Button>
                  )}
                  {by && canWrite && (
                    <Button
                      aria-label={`Remove ${purpose}`}
                      disabled={revoke.isPending}
                      onClick={() => revoke.mutate(by)}
                      size="sm"
                      title="Remove the agent from the grant that allows this, for all of its purposes"
                      variant="ghost"
                    >
                      <X className="size-4" />
                    </Button>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </section>

      <ModelKey
        bindings={bindings.data ?? []}
        canGrant={canGrant}
        covered={(bindingId) =>
          covers(mine, bindingId, MODEL_PURPOSE, 'file_descriptor')
        }
        isPending={save.isPending}
        loaded={bindings.isSuccess}
        onChange={(reference) => onChange({ ...value, modelKeyRef: reference })}
        onGrant={(binding) => ensure(binding, MODEL_PURPOSE, 'file_descriptor')}
        showGrant={Boolean(agent) && canRead}
        value={value.modelKeyRef}
      />

      {agent && canRead && (
        <AgentSecrets
          agent={agent}
          bindings={(bindings.data ?? []).filter(
            (b) => b.enabled && b.id !== github?.id && mayGrant(b),
          )}
          canWrite={canWrite}
          error={save.error}
          isPending={save.isPending || revoke.isPending}
          onGrant={(binding, purpose, done) =>
            ensure(binding, purpose, 'environment', done)
          }
          onRemove={canWrite ? (g) => revoke.mutate(g) : undefined}
          purposes={purposeSuggestions(grants.data ?? [])}
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
  onRemove,
  purposes,
  rows,
}: {
  agent: { id: string; name: string }
  bindings: SecretBinding[]
  canWrite: boolean
  error: unknown
  isPending: boolean
  onGrant: (binding: SecretBinding, purpose: string, done: () => void) => void
  /** Unset when the user cannot remove access. */
  onRemove?: (grant: SecretGrant) => void
  purposes: string[]
  rows: AccessRow[]
}) {
  const [adding, setAdding] = useState(false)
  // run_with_secret delivers by environment; anything else is a setup
  // secret of the runner.
  const agentRows = rows.filter((r) =>
    r.grant.delivery_modes.includes('environment'),
  )
  const runnerRows = rows.filter(
    (r) => !r.grant.delivery_modes.includes('environment'),
  )
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
        environment of one command. Change a grant in{' '}
        <Link
          className="text-action hover:underline"
          to={agentsPath('secrets')}
        >
          Agents › Settings › Secrets
        </Link>
        .
      </p>
      {agentRows.length === 0 ? (
        <p className="text-tertiary text-sm">
          No grant lets the agent request a secret.
        </p>
      ) : (
        <GrantTable
          isPending={isPending}
          onRemove={onRemove}
          rows={agentRows}
        />
      )}
      {runnerRows.length > 0 && (
        <>
          <p className="text-tertiary mt-2 text-xs">
            Used by the runner for the agent, never given to it: the model key,
            the repository tokens, and the MCP header tokens.
          </p>
          <GrantTable
            isPending={isPending}
            onRemove={onRemove}
            rows={runnerRows}
          />
        </>
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
              description:
                'What the agent uses it for, e.g. npm or sentry. Pick one or type a new one.',
              kind: 'combobox',
              label: 'Purpose',
              name: 'purpose',
              options: purposes.map((p) => ({ label: p, value: p })),
              required: true,
            },
          ]}
          isPending={isPending}
          onClose={() => setAdding(false)}
          onSubmit={(values) => {
            const binding = bindings.find((b) => b.id === values.binding)
            if (!binding) return
            const purpose = String(values.purpose)
            if ((SETUP_PURPOSES as readonly string[]).includes(purpose)) {
              toast.error(`${purpose} is for the runner only`)
              return
            }
            if (
              covers(
                rows.map((r) => r.grant),
                binding.id,
                purpose,
                'environment',
              )
            ) {
              toast.info(
                `${binding.reference} is already granted for ${purpose}`,
              )
              setAdding(false)
              return
            }
            onGrant(binding, purpose, () => setAdding(false))
          }}
          title="Add access"
        />
      )}
    </section>
  )
}

function GrantTable({
  isPending,
  onRemove,
  rows,
}: {
  isPending: boolean
  onRemove?: (grant: SecretGrant) => void
  rows: AccessRow[]
}) {
  return (
    <table className="w-full text-sm">
      <thead className="text-tertiary text-left text-xs">
        <tr>
          <th className="py-1 font-normal">Reference</th>
          <th className="py-1 font-normal">Purposes</th>
          <th className="py-1 font-normal">Delivery</th>
          <th className="py-1 font-normal">TTL</th>
          {onRemove && <th />}
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
            <td className="py-2 font-mono text-xs">{grant.max_ttl_seconds}s</td>
            {onRemove && (
              <td className="py-2 text-right">
                <Button
                  aria-label={`Remove ${binding.reference}`}
                  disabled={isPending}
                  onClick={() => onRemove(grant)}
                  size="sm"
                  title={
                    grant.binding_ids.length > 1
                      ? 'Remove the agent from this grant, for all of its secrets'
                      : 'Remove the agent from this grant'
                  }
                  variant="ghost"
                >
                  <X className="size-4" />
                </Button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  )
}

/**
 * The agent's model key. Empty uses the key of the organization's
 * model upstream. The broker gives the key to the runner only when a
 * model_inference grant names the agent and the binding.
 */
function ModelKey({
  bindings,
  canGrant,
  covered,
  isPending,
  loaded,
  onChange,
  onGrant,
  showGrant,
  value,
}: {
  bindings: SecretBinding[]
  canGrant: (binding: SecretBinding) => boolean
  covered: (bindingId: string) => boolean
  isPending: boolean
  loaded: boolean
  onChange: (reference: string) => void
  onGrant: (binding: SecretBinding) => void
  showGrant: boolean
  value: string
}) {
  const references = fieldReferences(bindings.filter(canSupplyRunner))
  // Keep a saved value visible after its binding is gone or disabled.
  if (value && !references.includes(value)) references.push(value)
  const [, field] = value.split('#')
  const binding = bindingOf(bindings, value)
  // A field that is not in the field list is not usable. A binding
  // without a field list accepts only a reference without a field.
  const usable = binding
    ? canSupplyRunner(binding) &&
      (binding.allowed_fields.length
        ? binding.allowed_fields.includes(field ?? '')
        : field === undefined)
    : false
  const ok = binding ? covered(binding.id) : false
  return (
    <section className="flex flex-col gap-3">
      <div className="text-overline text-tertiary uppercase">Model key</div>
      <Field
        help="The key that the runner uses for model calls. Saved with the agent."
        htmlFor="agent-model-key"
        label="Binding"
      >
        <Select
          onValueChange={(next) => onChange(next === ORG_KEY ? '' : next)}
          value={value || ORG_KEY}
        >
          <SelectTrigger
            aria-label="Model key binding"
            className="text-sm"
            id="agent-model-key"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ORG_KEY}>The organization's key</SelectItem>
            {references.map((reference) => (
              <SelectItem key={reference} value={reference}>
                {reference}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      {loaded && value && !binding && (
        <p className="text-danger text-sm">
          This binding does not exist. Select a different binding.
        </p>
      )}
      {binding && !usable && (
        <p className="text-danger text-sm">
          This binding cannot supply a model key. Select a different binding.
        </p>
      )}
      {binding && usable && showGrant && (
        <div className="border-tertiary flex items-center gap-3 rounded-lg border px-3 py-2">
          {ok ? (
            <Check className="text-success size-4" />
          ) : (
            <X className="text-tertiary size-4" />
          )}
          <span className="flex-1 text-sm">Call the model</span>
          <span className="text-tertiary font-mono text-xs">
            {MODEL_PURPOSE}
          </span>
          {!ok && canGrant(binding) && (
            <Button
              disabled={isPending}
              onClick={() => onGrant(binding)}
              size="sm"
              variant="outline"
            >
              Grant
            </Button>
          )}
        </div>
      )}
    </section>
  )
}
