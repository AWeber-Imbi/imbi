import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { formatDistanceToNow } from 'date-fns'
import { Check, ExternalLink, Loader2, Rocket } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  compareDeploymentRefs,
  listCurrentReleases,
  listDeploymentRefs,
  listRefCommits,
  triggerDeployment,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LoadingState } from '@/components/ui/loading-state'
import { extractApiErrorDetail } from '@/lib/apiError'
import { ciStatusDotClass } from '@/lib/status-colors'
import { cn, sortEnvironments } from '@/lib/utils'
import type {
  CurrentReleaseEnvironment,
  DeploymentCommit,
  DeploymentRef,
  Environment,
} from '@/types'

interface DeployTabProps {
  environments: Environment[]
  initialEnvSlug?: string
  onClose: () => void
  onRunStarted?: (run: import('./DeploymentModal').DeploymentRunStarted) => void
  // Modal-open gate: queries only fire while the modal is open so the
  // hidden DeployTab doesn't issue GitHub round-trips on every page load.
  open: boolean
  orgSlug: string
  projectId: string
}

interface SelectedVersion {
  label: null | string
  sha: string
}

export function DeployTab({
  environments,
  initialEnvSlug,
  onClose,
  onRunStarted,
  open,
  orgSlug,
  projectId,
}: DeployTabProps) {
  const sorted = useMemo(() => sortEnvironments(environments), [environments])
  const [envSlug, setEnvSlug] = useState<string>(
    initialEnvSlug ?? sorted[sorted.length - 1]?.slug ?? '',
  )
  useEffect(() => {
    // Reset to the requested env whenever the modal is reopened with
    // a different chip.  ``envSlug`` is intentionally excluded — listing
    // it would re-snap to ``initialEnvSlug`` after the user picks
    // another env card.
    if (initialEnvSlug && initialEnvSlug !== envSlug) setEnvSlug(initialEnvSlug)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialEnvSlug])

  const env = sorted.find((e) => e.slug === envSlug) ?? sorted[0]

  const { data: currentReleases = [] } = useQuery<CurrentReleaseEnvironment[]>({
    enabled: open && !!orgSlug && !!projectId,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, projectId, signal),
    queryKey: ['currentReleases', orgSlug, projectId],
  })
  const currentByEnv = useMemo(() => {
    const map = new Map<string, CurrentReleaseEnvironment>()
    for (const row of currentReleases) map.set(row.environment.slug, row)
    return map
  }, [currentReleases])
  const current = env ? currentByEnv.get(env.slug) : undefined

  // For the first env (e.g. Testing) we list commits on the default
  // branch.  For staging / production we list tags.
  const isFirstEnv = env?.slug === sorted[0]?.slug

  const { data: refs = [] } = useQuery<DeploymentRef[]>({
    enabled: open && !!env,
    queryFn: ({ signal }) =>
      listDeploymentRefs(
        orgSlug,
        projectId,
        { kind: isFirstEnv ? 'default' : 'tag' },
        signal,
      ),
    queryKey: [
      'deploymentRefs',
      orgSlug,
      projectId,
      isFirstEnv ? 'branch' : 'tag',
    ],
  })

  const defaultBranchName = useMemo(() => {
    const def = refs.find((r) => r.is_default)
    return def?.name ?? 'main'
  }, [refs])

  const { data: branchCommits = [], isLoading: commitsLoading } = useQuery<
    DeploymentCommit[]
  >({
    enabled: open && !!env && isFirstEnv,
    queryFn: ({ signal }) =>
      listRefCommits(
        orgSlug,
        projectId,
        defaultBranchName,
        { limit: 25 },
        signal,
      ),
    queryKey: ['refCommits', orgSlug, projectId, defaultBranchName],
  })

  const tagOptions = useMemo<DeploymentRef[]>(
    () => (isFirstEnv ? [] : refs.filter((r) => r.kind === 'tag')),
    [isFirstEnv, refs],
  )

  const [selected, setSelected] = useState<null | SelectedVersion>(null)
  useEffect(() => {
    setSelected(null)
  }, [envSlug])

  // For first-env (commit-based) deployments, ``selected.label`` is the
  // branch name (e.g. ``main``), so compare against ``selected.sha``.
  // For tag-based envs ``selected.label`` is the tag and matches
  // ``current.release.version``.
  const isRedeploy =
    !!current?.release &&
    !!selected &&
    (isFirstEnv
      ? current.release.version === selected.sha ||
        selected.sha.startsWith(current.release.version) ||
        current.release.version.startsWith(selected.sha)
      : current.release.version === selected.label)

  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: (payload: SelectedVersion) =>
      triggerDeployment(orgSlug, projectId, {
        action: isRedeploy ? 'redeploy' : 'deploy',
        committish: payload.sha,
        environment: envSlug,
        ref_label: payload.label,
      }),
    onError: (err) => {
      toast.error(
        err instanceof ApiError
          ? (extractApiErrorDetail(err) ?? err.message)
          : (err as Error).message,
      )
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({
        queryKey: ['currentReleases', orgSlug, projectId],
      })
      const url = data.run.run_url
      const envName = env?.name ?? envSlug
      if (onRunStarted && data.run.run_id) {
        const toastId = toast.loading(`Deploying to ${envName}…`, {
          action: url
            ? {
                label: 'View run',
                onClick: () => window.open(url, '_blank', 'noopener'),
              }
            : undefined,
          description: data.run.status
            ? `status: ${data.run.status}`
            : undefined,
          icon: <Loader2 className="h-4 w-4 animate-spin" />,
        })
        onRunStarted({
          actionLabel: url ? 'View run' : undefined,
          actionUrl: url,
          envName,
          initialStatus: data.run.status,
          originOrgSlug: orgSlug,
          originProjectId: projectId,
          runId: data.run.run_id,
          runUrl: url,
          toastId,
        })
      } else {
        toast.success(
          `Workflow dispatched to ${envName}`,
          url
            ? {
                action: {
                  label: 'View run',
                  onClick: () => window.open(url, '_blank', 'noopener'),
                },
              }
            : undefined,
        )
      }
      onClose()
    },
  })

  const onDeploy = () => {
    if (!selected) return
    mutation.mutate(selected)
  }

  return (
    <div className="flex flex-col gap-4">
      {/* Step 1 — environment pickers */}
      <section>
        <p className="mb-2 text-xs uppercase tracking-wider text-tertiary">
          Step 1 — Environment
        </p>
        <div className="grid grid-cols-3 gap-2">
          {sorted.map((e) => {
            const row = currentByEnv.get(e.slug)
            const active = e.slug === envSlug
            return (
              <button
                className={cn(
                  'rounded-md border p-3 text-left transition-colors',
                  active
                    ? 'border-action bg-action/5'
                    : 'border-secondary hover:bg-tertiary/30',
                )}
                key={e.slug}
                onClick={() => setEnvSlug(e.slug)}
                type="button"
              >
                <div className="text-sm font-medium">{e.name}</div>
                <div className="mt-1 text-xs text-tertiary">
                  {row?.release ? (
                    <>
                      <span className="font-mono">{row.release.version}</span>
                      {row.last_event_at ? (
                        <>
                          {' · '}
                          {formatDistanceToNow(new Date(row.last_event_at), {
                            addSuffix: true,
                          })}
                        </>
                      ) : null}
                    </>
                  ) : (
                    'not deployed'
                  )}
                </div>
              </button>
            )
          })}
        </div>
      </section>

      {/* Step 2 — version picker */}
      <section className="min-h-[180px]">
        <p className="mb-2 text-xs uppercase tracking-wider text-tertiary">
          {`Step 2 — ${isFirstEnv ? `Commit on ${defaultBranchName}` : 'Tag'}`}
        </p>
        {isFirstEnv ? (
          <CommitList
            commits={branchCommits}
            current={current?.release?.version ?? null}
            isLoading={commitsLoading}
            onSelect={(c) =>
              setSelected({ label: defaultBranchName, sha: c.sha })
            }
            selectedSha={selected?.sha ?? null}
          />
        ) : (
          <TagList
            current={current?.release?.version ?? null}
            onSelect={(r) => setSelected({ label: r.name, sha: r.sha })}
            selectedSha={selected?.sha ?? null}
            tags={tagOptions}
          />
        )}
      </section>

      {/* Diff summary */}
      {selected && current?.release ? (
        <DiffSummary
          base={current.release.version}
          head={selected.label ?? selected.sha}
          orgSlug={orgSlug}
          projectId={projectId}
        />
      ) : null}

      {/* Footer */}
      <div className="bg-secondary/30 -mx-6 -mb-6 mt-2 flex items-center justify-end gap-2 border-t border-tertiary px-6 py-3">
        <Button onClick={onClose} type="button" variant="ghost">
          Cancel
        </Button>
        <Button
          disabled={!selected || mutation.isPending}
          onClick={onDeploy}
          type="button"
        >
          {mutation.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Rocket className="mr-1 h-4 w-4" />
          )}
          {`${isRedeploy ? 'Redeploy' : 'Deploy'} ${
            selected?.label ?? selected?.sha.slice(0, 7) ?? ''
          } to ${env?.name ?? envSlug}`}
        </Button>
      </div>
    </div>
  )
}

function CommitList({
  commits,
  current,
  isLoading,
  onSelect,
  selectedSha,
}: {
  commits: DeploymentCommit[]
  current: null | string
  isLoading: boolean
  onSelect: (commit: DeploymentCommit) => void
  selectedSha: null | string
}) {
  if (isLoading) return <LoadingState label="Loading commits…" />
  if (commits.length === 0)
    return (
      <p className="rounded-md border border-secondary p-3 text-sm text-tertiary">
        No commits available.
      </p>
    )
  return (
    <ul className="max-h-[260px] overflow-y-auto rounded-md border border-secondary">
      {commits.map((c) => {
        const active = c.sha === selectedSha
        const isCurrent = current ? c.sha.startsWith(current) : false
        return (
          <li
            className={cn(
              'flex items-center gap-3 border-b border-tertiary px-3 py-2 last:border-b-0',
              active && 'bg-action/5',
            )}
            key={c.sha}
          >
            <button
              className="flex flex-1 items-center gap-3 text-left"
              onClick={() => onSelect(c)}
              type="button"
            >
              <span
                aria-label={`CI ${c.ci_status}`}
                className={cn(
                  'inline-block h-2 w-2 rounded-full',
                  ciStatusDotClass(c.ci_status),
                )}
              />
              <span className="font-mono text-xs">{c.short_sha}</span>
              <span className="flex-1 truncate text-sm">{c.message}</span>
              <span className="shrink-0 text-xs text-tertiary">{c.author}</span>
              {c.is_head ? <Badge variant="outline">HEAD</Badge> : null}
              {isCurrent ? <Badge variant="neutral">current</Badge> : null}
              {active ? <Check className="text-action h-4 w-4" /> : null}
            </button>
            {c.url ? (
              <a
                aria-label="View commit on GitHub"
                className="text-tertiary hover:text-primary"
                href={c.url}
                rel="noopener"
                target="_blank"
              >
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

function DiffSummary({
  base,
  head,
  orgSlug,
  projectId,
}: {
  base: string
  head: string
  orgSlug: string
  projectId: string
}) {
  const { data, isLoading } = useQuery({
    enabled: base !== head,
    queryFn: ({ signal }) =>
      compareDeploymentRefs(orgSlug, projectId, base, head, undefined, signal),
    queryKey: ['compare', orgSlug, projectId, base, head],
  })
  if (base === head)
    return (
      <p className="text-xs text-tertiary">
        Re-deploying — no commit delta to summarize.
      </p>
    )
  if (isLoading || !data) return null
  return (
    <div className="bg-tertiary/20 rounded-md border border-secondary p-3 text-xs">
      <div className="font-mono text-tertiary">
        {base} → {head}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        <span>{data.commits.length} commits</span>
        <span>{data.files_changed} files changed</span>
        <span className="text-success">+{data.additions}</span>
        <span className="text-danger">−{data.deletions}</span>
      </div>
    </div>
  )
}

function TagList({
  current,
  onSelect,
  selectedSha,
  tags,
}: {
  current: null | string
  onSelect: (tag: DeploymentRef) => void
  selectedSha: null | string
  tags: DeploymentRef[]
}) {
  if (tags.length === 0)
    return (
      <p className="rounded-md border border-secondary p-3 text-sm text-tertiary">
        No tags available.
      </p>
    )
  return (
    <ul className="max-h-[260px] overflow-y-auto rounded-md border border-secondary">
      {tags.map((t) => {
        const active = t.sha === selectedSha
        const isCurrent = t.name === current
        return (
          <li
            className={cn(
              'flex items-center justify-between border-b border-tertiary px-3 py-2 last:border-b-0',
              active && 'bg-action/5',
            )}
            key={t.sha}
          >
            <button
              className="flex flex-1 items-center gap-3 text-left"
              onClick={() => onSelect(t)}
              type="button"
            >
              <span className="font-mono text-sm">{t.name}</span>
              <span className="font-mono text-xs text-tertiary">
                {t.sha.slice(0, 7)}
              </span>
              {isCurrent ? <Badge variant="neutral">current</Badge> : null}
              {active ? <Check className="text-action h-4 w-4" /> : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
