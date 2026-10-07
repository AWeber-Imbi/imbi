import { useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  deleteAgent,
  listAgentVersions,
  restoreAgentVersion,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Sk } from '@/components/ui/skeleton'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatRelativeDate } from '@/lib/formatDate'
import { queryKeys } from '@/lib/queryKeys'
import type { Agent, AgentVersion } from '@/types'

import { AGENT_PROMPT_LABEL } from './agentDraft'
import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'

interface VersionHistoryTabProps {
  agent: Agent
  orgSlug: string
}

export function VersionHistoryTab({ agent, orgSlug }: VersionHistoryTabProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canDelete = useHasPermission('agent:delete')
  const canWrite = useHasPermission('agent:write')
  const [restoreTarget, setRestoreTarget] = useState<AgentVersion | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const restoreMove = restoreTarget && restoreLabelMove(restoreTarget)
  // The API refuses to delete an agent that other agents delegate to.
  const delegators = (useAgentList(orgSlug).data ?? []).filter((a) =>
    a.subagents?.some((s) => s.agent_id === agent.id),
  )
  const locked = delegators.length > 0

  const versions = useQuery({
    queryFn: ({ signal }) => listAgentVersions(orgSlug, agent.slug, signal),
    queryKey: queryKeys.agentVersions(orgSlug, agent.slug),
  })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.agents(orgSlug) })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.agentVersions(orgSlug, agent.slug),
    })
  }

  const restore = useMutation({
    mutationFn: (n: number) => restoreAgentVersion(orgSlug, agent.slug, n),
    onError: (error) =>
      toast.error(`Failed to restore: ${extractApiErrorDetail(error)}`),
    onSuccess: (restored, n) => {
      refresh()
      // A restore can move the prompt label, so reload the prompts.
      void queryClient.invalidateQueries({ queryKey: queryKeys.prompts() })
      toast.success(`Restored v${n}`)
      navigate(agentsPath('manage', restored.slug))
    },
  })

  const remove = useMutation({
    mutationFn: () => deleteAgent(orgSlug, agent.slug),
    onError: (error) =>
      toast.error(
        `Failed to delete the agent: ${extractApiErrorDetail(error)}`,
      ),
    onSuccess: () => {
      refresh()
      toast.success(`Deleted ${agent.name}`)
      navigate(agentsPath('manage'))
    },
  })

  return (
    <div className="flex flex-col gap-4">
      {versions.error ? (
        <ErrorBanner error={versions.error} title="Failed to load versions" />
      ) : (
        <div className="border-border bg-card overflow-hidden rounded-lg border">
          {versions.isLoading && (
            <div className="flex flex-col gap-3 p-5">
              <Sk h={20} r={4} />
              <Sk h={20} r={4} />
            </div>
          )}
          {versions.data?.map((v) => {
            const current = v.n === agent.version
            return (
              <div
                className="border-border flex items-center gap-4 border-b px-5 py-3 last:border-b-0"
                key={v.n}
              >
                <span className="w-8.5 font-mono text-sm font-semibold tabular-nums">
                  v{v.n}
                </span>
                {current && <Badge variant="success">Current</Badge>}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">
                    {v.summary || 'No summary'}
                  </div>
                  <div className="text-tertiary text-xs">
                    {formatRelativeDate(v.created_at)} · {v.created_by}
                    {v.snapshot.prompt_version != null &&
                      ` · prompt v${v.snapshot.prompt_version}`}
                  </div>
                </div>
                {!current && canWrite && (
                  <Button
                    disabled={restore.isPending}
                    onClick={() => setRestoreTarget(v)}
                    size="sm"
                    variant="outline"
                  >
                    Restore
                  </Button>
                )}
              </div>
            )
          })}
        </div>
      )}

      {canDelete && (
        <div className="border-destructive bg-card rounded-lg border p-6">
          <div className="text-overline text-destructive uppercase">
            Delete agent
          </div>
          <div className="mt-2 flex items-center gap-6">
            <p className="text-secondary flex-1 text-sm text-pretty">
              {locked
                ? `${agent.name} is a subagent of ${delegators.length} agent${delegators.length === 1 ? '' : 's'}. Remove it from each agent below before it can be deleted.`
                : 'Deletes the agent and its version history. Its prompt stays in the prompt CMS.'}
            </p>
            <Button
              disabled={locked || remove.isPending}
              onClick={() => setConfirmDelete(true)}
              size="sm"
              variant="destructive"
            >
              Delete agent
            </Button>
          </div>
          {locked && (
            <div className="border-border mt-4 flex flex-col gap-2 border-t pt-4">
              {delegators.map((d) => (
                <div className="flex items-center gap-3 text-sm" key={d.id}>
                  <Link
                    className="text-action hover:underline"
                    to={agentsPath('manage', d.slug)}
                  >
                    {d.name}
                  </Link>
                  <span className="text-tertiary font-mono text-xs">
                    {d.slug}
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        confirmLabel="Restore"
        description={`This writes a new version with the configuration of v${restoreTarget?.n}.${restoreMove ? ` The system prompt and model come back too. Moves ${restoreMove}.` : ''} Unsaved edits on this page are lost.`}
        onCancel={() => setRestoreTarget(null)}
        onConfirm={() => {
          if (restoreTarget !== null) restore.mutate(restoreTarget.n)
          setRestoreTarget(null)
        }}
        open={restoreTarget !== null}
        title={`Restore v${restoreTarget?.n}?`}
      />
      <ConfirmDialog
        confirmLabel="Delete agent"
        description={`This deletes ${agent.name} and all of its versions. You cannot undo this. The agent's prompt${agent.prompt_ref ? ` (${agent.prompt_ref})` : ''} is not deleted; it stays in the prompt CMS.`}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => {
          setConfirmDelete(false)
          remove.mutate()
        }}
        open={confirmDelete}
        title={`Delete ${agent.name}?`}
      />
    </div>
  )
}

/**
 * Name the label move that a restore of `version` does, for example
 * `agents/mender@stable to prompt v3`. Return null when no label moves.
 */
function restoreLabelMove(version: AgentVersion): null | string {
  const { prompt_ref: ref, prompt_version: n } = version.snapshot
  if (!ref || n == null) return null
  const [address, selector] = ref.split('@', 2)
  // A reference that names a version number moves no label.
  if (selector && /^\d+$/.test(selector)) return null
  return `${address}@${selector || AGENT_PROMPT_LABEL} to prompt v${n}`
}
