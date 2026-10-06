import { useState } from 'react'

import { useNavigate } from 'react-router-dom'

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
import type { Agent } from '@/types'

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
  const [restoreTarget, setRestoreTarget] = useState<null | number>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)

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
                  </div>
                </div>
                {!current && canWrite && (
                  <Button
                    disabled={restore.isPending}
                    onClick={() => setRestoreTarget(v.n)}
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
              Deletes the agent and its version history. Its prompt stays in the
              prompt CMS.
            </p>
            <Button
              disabled={remove.isPending}
              onClick={() => setConfirmDelete(true)}
              size="sm"
              variant="destructive"
            >
              Delete agent
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        confirmLabel="Restore"
        description={`This writes a new version with the configuration of v${restoreTarget}. The system prompt and model are not part of an agent version, so they do not change. Unsaved edits on this page are lost.`}
        onCancel={() => setRestoreTarget(null)}
        onConfirm={() => {
          if (restoreTarget !== null) restore.mutate(restoreTarget)
          setRestoreTarget(null)
        }}
        open={restoreTarget !== null}
        title={`Restore v${restoreTarget}?`}
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
