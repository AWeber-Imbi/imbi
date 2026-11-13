import { useState } from 'react'

import { Link } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleHelp } from 'lucide-react'
import { toast } from 'sonner'

import {
  findSideEffectDeployments,
  listStaleSideEffects,
  resolveSideEffect,
} from '@/api/endpoints'
import { agentsPath } from '@/components/agents/agentsNav'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type { DeploymentRun } from '@/types'

import type { SideEffectResolve, StaleSideEffect } from './types'

const ACTION: Record<string, string> = {
  deployment: 'Deployment',
  'failure-notice': 'Failure notice',
  'step-email': 'Step email',
}

/**
 * Side effects of workflow runs that started and did not finish. A
 * repeat of such a call gets `outcome_unknown`, so only an operator
 * resolves it (ADR 0021). Hidden without `workflow:recover`.
 */
export function StaleSideEffects({ orgSlug }: { orgSlug: string }) {
  const canRecover = useHasPermission('workflow:recover', orgSlug)
  const effects = useQuery({
    enabled: canRecover,
    queryFn: ({ signal }) => listStaleSideEffects(orgSlug, signal),
    queryKey: queryKeys.workflowSideEffects(orgSlug),
  })
  if (!canRecover || (!effects.isError && !effects.data?.length)) return null
  return (
    <section className="border-tertiary mb-6 rounded-lg border">
      <header className="border-tertiary flex items-baseline gap-2 border-b px-4 py-2.5">
        <CircleHelp className="text-warning size-3.5 self-center" />
        <span className="font-medium">Calls with an unknown outcome</span>
        <span className="text-tertiary text-xs">
          Started more than 15 minutes ago and did not finish. Check what
          happened, then resolve each one.
        </span>
      </header>
      {effects.isError ? (
        <div className="flex items-center gap-3 px-4 py-2 text-sm">
          <span className="text-danger">
            Failed to load the calls: {extractApiErrorDetail(effects.error)}
          </span>
          <Button
            className="h-7 px-2 text-xs"
            disabled={effects.isFetching}
            onClick={() => void effects.refetch()}
            size="sm"
            variant="outline"
          >
            Retry
          </Button>
        </div>
      ) : (
        effects.data?.map((effect) => (
          <EffectRow effect={effect} key={effect.key} orgSlug={orgSlug} />
        ))
      )}
    </section>
  )
}

/** The deployments that the provider found for a deployment call. */
function Candidates({
  error,
  isPending,
  onUse,
  runs,
}: {
  error: Error | null
  isPending: boolean
  onUse: (runId: string) => void
  runs: DeploymentRun[] | undefined
}) {
  let body
  if (error) {
    body = (
      <span className="text-danger">
        Failed to search the deployment provider: {extractApiErrorDetail(error)}
      </span>
    )
  } else if (isPending) {
    body = (
      <span className="text-tertiary">Searching the deployment provider…</span>
    )
  } else if (!runs?.length) {
    body = (
      <span className="text-tertiary">
        The deployment provider has no deployment of this version since the
        call. Clear the call to deploy again.
      </span>
    )
  } else {
    body = runs.map((run) => (
      <div className="flex items-center gap-3" key={run.run_id}>
        {run.run_url ? (
          <a
            className="hover:text-action font-medium"
            href={run.run_url}
            rel="noreferrer"
            target="_blank"
          >
            Deployment {run.run_id}
          </a>
        ) : (
          <span className="font-medium">Deployment {run.run_id}</span>
        )}
        <span className="text-secondary">{run.status}</span>
        {run.started_at && (
          <RelativeTime className="text-tertiary" value={run.started_at} />
        )}
        <Button
          className="ml-auto h-6 px-2 text-xs"
          onClick={() => onUse(run.run_id)}
          size="sm"
          variant="outline"
        >
          Use this deployment
        </Button>
      </div>
    ))
  }
  return (
    <div className="col-span-4 flex flex-col gap-1.5 pl-33 text-xs">{body}</div>
  )
}

/** What a resolution does, for the confirm dialog. */
function describe(
  effect: StaleSideEffect,
  resolution: SideEffectResolve['resolution'],
  retry: boolean,
  deploymentRunId: null | string,
): string {
  const parts = deploymentRunId
    ? [
        `Imbi records deployment ${deploymentRunId} as the result of the ` +
          'call. Another deploy of the same version at that time also ' +
          'matches: make sure that this is the deployment of the call.',
      ]
    : resolution === 'mark_done'
      ? [
          'Imbi records that the call acted, and does not make it again.' +
            (effect.action === 'deployment'
              ? ' The step cannot run again: Imbi does not know the deployment.'
              : ''),
        ]
      : effect.action === 'deployment'
        ? [
            'Imbi forgets the call. Check the deployment provider first: if ' +
              'the deployment started, a retry deploys again.',
          ]
        : ['Imbi forgets the call.']
  if (retry) parts.push('The run opens again and the step runs again.')
  return parts.join(' ')
}

function EffectRow({
  effect,
  orgSlug,
}: {
  effect: StaleSideEffect
  orgSlug: string
}) {
  const queryClient = useQueryClient()
  const [retry, setRetry] = useState(effect.retryable)
  const [pending, setPending] = useState<
    null | SideEffectResolve['resolution']
  >(null)
  // The deployment run that the operator selected from the provider.
  const [confirmRun, setConfirmRun] = useState<null | string>(null)
  const [searched, setSearched] = useState(false)
  const deployments = useQuery({
    enabled: searched,
    queryFn: ({ signal }) =>
      findSideEffectDeployments(orgSlug, effect.key, signal),
    queryKey: queryKeys.workflowSideEffectDeployments(orgSlug, effect.key),
  })
  const resolve = useMutation({
    mutationFn: (body: SideEffectResolve) => resolveSideEffect(orgSlug, body),
    onError: (error) => {
      toast.error(`Failed to resolve the call: ${extractApiErrorDetail(error)}`)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflowSideEffects(orgSlug),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.workflowAttention(orgSlug),
      })
    },
    onSuccess: (_, body) => {
      toast.success(body.retry ? 'Resolved. The step runs again.' : 'Resolved.')
    },
  })
  // Imbi does not know the run of a deployment marked done with no
  // confirmed run. A later list can find the step no longer retryable.
  const willRetry =
    retry &&
    effect.retryable &&
    !(pending === 'mark_done' && effect.action === 'deployment' && !confirmRun)
  const input = Object.entries(effect.step_input ?? {})
    .filter(([, value]) => ['number', 'string'].includes(typeof value))
    .map(([name, value]) => `${name}: ${String(value)}`)
    .join(', ')
  const runLink = `${agentsPath('workflows', effect.workflow_slug)}?run=${effect.run_id}`
  return (
    <div className="border-tertiary grid grid-cols-[120px_minmax(0,2fr)_100px_auto] items-center gap-3 border-b px-4 py-2 text-sm last:border-b-0">
      <span className="text-warning">
        {ACTION[effect.action] ?? effect.action}
      </span>
      <div className="flex min-w-0 flex-col">
        <Link className="hover:text-action truncate" to={runLink}>
          <span className="font-medium">{effect.workflow_name}</span>
          {effect.node_key && (
            <span className="text-tertiary"> · {effect.node_key}</span>
          )}
        </Link>
        {input && (
          <span className="text-tertiary truncate text-xs" title={input}>
            {input}
          </span>
        )}
      </div>
      <RelativeTime
        className="text-tertiary text-right text-xs"
        value={effect.created_at}
      />
      <div className="flex items-center justify-end gap-2">
        {effect.action === 'deployment' && (
          <Button
            className="h-7 px-2 text-xs"
            disabled={deployments.isFetching}
            onClick={() =>
              searched ? void deployments.refetch() : setSearched(true)
            }
            size="sm"
            variant="outline"
          >
            Find deployment
          </Button>
        )}
        {effect.retryable && (
          <label className="text-secondary flex items-center gap-1.5 text-xs">
            <Checkbox
              checked={retry}
              onCheckedChange={(value) => setRetry(value === true)}
            />
            Retry step
          </label>
        )}
        <Button
          className="h-7 px-2 text-xs"
          disabled={resolve.isPending}
          onClick={() => setPending('mark_done')}
          size="sm"
          variant="outline"
        >
          Mark done
        </Button>
        <Button
          className="h-7 px-2 text-xs"
          disabled={resolve.isPending}
          onClick={() => setPending('clear')}
          size="sm"
          variant="outline"
        >
          Clear
        </Button>
      </div>
      {searched && (
        <Candidates
          error={deployments.error}
          isPending={deployments.isPending}
          onUse={(runId) => {
            setConfirmRun(runId)
            setPending('mark_done')
          }}
          runs={deployments.data}
        />
      )}
      <ConfirmDialog
        confirmLabel={
          confirmRun
            ? 'Use deployment'
            : pending === 'mark_done'
              ? 'Mark done'
              : 'Clear'
        }
        description={
          pending ? describe(effect, pending, willRetry, confirmRun) : undefined
        }
        onCancel={() => {
          setPending(null)
          setConfirmRun(null)
        }}
        onConfirm={() => {
          if (pending) {
            resolve.mutate({
              deployment_run_id: confirmRun,
              key: effect.key,
              resolution: pending,
              retry: willRetry,
            })
          }
          setPending(null)
          setConfirmRun(null)
        }}
        open={pending !== null}
        title={`Resolve the ${(ACTION[effect.action] ?? effect.action).toLowerCase()} call?`}
      />
    </div>
  )
}
