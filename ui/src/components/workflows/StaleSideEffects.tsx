import { useState } from 'react'

import { Link } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CircleHelp } from 'lucide-react'
import { toast } from 'sonner'

import { listStaleSideEffects, resolveSideEffect } from '@/api/endpoints'
import { agentsPath } from '@/components/agents/agentsNav'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

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
  if (!canRecover || !effects.data?.length) return null
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
      {effects.data.map((effect) => (
        <EffectRow effect={effect} key={effect.key} orgSlug={orgSlug} />
      ))}
    </section>
  )
}

/** What a resolution does, for the confirm dialog. */
function describe(
  effect: StaleSideEffect,
  resolution: SideEffectResolve['resolution'],
  retry: boolean,
): string {
  const parts =
    resolution === 'mark_done'
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
  // Imbi does not know the run of a deployment marked done.
  const willRetry =
    retry && !(pending === 'mark_done' && effect.action === 'deployment')
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
      <ConfirmDialog
        confirmLabel={pending === 'mark_done' ? 'Mark done' : 'Clear'}
        description={pending ? describe(effect, pending, willRetry) : undefined}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          if (pending) {
            resolve.mutate({
              key: effect.key,
              resolution: pending,
              retry: willRetry,
            })
          }
          setPending(null)
        }}
        open={pending !== null}
        title={`Resolve the ${(ACTION[effect.action] ?? effect.action).toLowerCase()} call?`}
      />
    </div>
  )
}
