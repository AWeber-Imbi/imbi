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
  // Env is locked at modal open time — the URL ``/deploy/<env>`` carries
  // the target, and re-deploys are scoped to that single env. No picker
  // is rendered; users navigate to a different chip to change env.
  // Resolve the env first so a stale ``initialEnvSlug`` falls back to the
  // first env *and* the slug used to display / dispatch matches.
  const env = initialEnvSlug
    ? (sorted.find((e) => e.slug === initialEnvSlug) ?? sorted[0])
    : sorted[0]
  const envSlug = env?.slug ?? ''

  const { data: currentReleases = [] } = useQuery<CurrentReleaseEnvironment[]>({
    enabled: open && !!orgSlug && !!projectId,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, projectId, signal),
    queryKey: ['currentReleases', orgSlug, projectId],
  })
  const current = useMemo(
    () =>
      env
        ? currentReleases.find((r) => r.environment.slug === env.slug)
        : undefined,
    [currentReleases, env],
  )

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

  // Phase 1.5 picker: on Testing the user can swap from the flat
  // default-branch commit list into a "Branches" pane that lists every
  // branch (filterable) and pulls commits for the chosen one on demand.
  const [pickerMode, setPickerMode] = useState<'branches' | 'default'>(
    'default',
  )
  const [branchQuery, setBranchQuery] = useState('')
  const [activeBranch, setActiveBranch] = useState<null | string>(null)
  useEffect(() => {
    setPickerMode('default')
    setActiveBranch(null)
    setBranchQuery('')
  }, [envSlug])

  const showBranchPane = isFirstEnv && pickerMode === 'branches'
  const { data: branchRefs = [], isLoading: branchesLoading } = useQuery<
    DeploymentRef[]
  >({
    enabled: open && showBranchPane,
    queryFn: ({ signal }) =>
      listDeploymentRefs(orgSlug, projectId, { kind: 'branch' }, signal),
    queryKey: ['deploymentRefs', orgSlug, projectId, 'branch'],
  })
  const filteredBranches = useMemo(() => {
    const q = branchQuery.trim().toLowerCase()
    if (!q) return branchRefs
    return branchRefs.filter((b) => b.name.toLowerCase().includes(q))
  }, [branchRefs, branchQuery])
  const { data: activeBranchCommits = [], isLoading: activeBranchLoading } =
    useQuery<DeploymentCommit[]>({
      enabled: open && showBranchPane && !!activeBranch,
      queryFn: ({ signal }) =>
        listRefCommits(
          orgSlug,
          projectId,
          activeBranch ?? '',
          { limit: 25 },
          signal,
        ),
      queryKey: ['refCommits', orgSlug, projectId, activeBranch],
    })

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
          icon: <Loader2 className="size-4 animate-spin" />,
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
      {/* Locked target environment */}
      <section>
        <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
          Environment
        </p>
        <div className="border-action bg-action/5 rounded-md border p-3">
          <div className="text-sm font-medium">{env?.name ?? envSlug}</div>
          <div className="text-tertiary mt-1 text-xs">
            {current?.release ? (
              <>
                <span className="font-mono">{current.release.version}</span>
                {current.last_event_at ? (
                  <>
                    {' · '}
                    {formatDistanceToNow(new Date(current.last_event_at), {
                      addSuffix: true,
                    })}
                  </>
                ) : null}
              </>
            ) : (
              'not deployed'
            )}
          </div>
        </div>
      </section>

      {/* Version picker */}
      <section className="min-h-45">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-tertiary text-xs tracking-wider uppercase">
            {isFirstEnv
              ? showBranchPane
                ? activeBranch
                  ? `Commit on ${activeBranch}`
                  : 'Pick a branch'
                : `Commit on ${defaultBranchName}`
              : 'Tag'}
          </p>
          {isFirstEnv ? (
            <PickerToggle
              defaultLabel={defaultBranchName}
              mode={pickerMode}
              onChange={(m) => {
                setPickerMode(m)
                setSelected(null)
                if (m === 'default') setActiveBranch(null)
              }}
            />
          ) : null}
        </div>
        {!isFirstEnv ? (
          <TagList
            current={current?.release?.version ?? null}
            onSelect={(r) => setSelected({ label: r.name, sha: r.sha })}
            selectedSha={selected?.sha ?? null}
            tags={tagOptions}
          />
        ) : showBranchPane ? (
          <BranchPicker
            activeBranch={activeBranch}
            branches={filteredBranches}
            branchesLoading={branchesLoading}
            commits={activeBranchCommits}
            commitsLoading={activeBranchLoading}
            current={current?.release?.version ?? null}
            onBranchSelect={(name) => {
              setActiveBranch(name)
              setSelected(null)
            }}
            onCommitSelect={(c) => {
              if (!activeBranch) return
              setSelected({ label: activeBranch, sha: c.sha })
            }}
            onQueryChange={setBranchQuery}
            query={branchQuery}
            selectedSha={selected?.sha ?? null}
          />
        ) : (
          <CommitList
            commits={branchCommits}
            current={current?.release?.version ?? null}
            isLoading={commitsLoading}
            onSelect={(c) =>
              setSelected({ label: defaultBranchName, sha: c.sha })
            }
            selectedSha={selected?.sha ?? null}
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
      <div className="border-tertiary bg-secondary/30 -mx-6 mt-2 -mb-4 flex items-center justify-end gap-2 border-t px-6 py-4">
        <Button onClick={onClose} type="button" variant="ghost">
          Cancel
        </Button>
        <Button
          disabled={!selected || mutation.isPending}
          onClick={onDeploy}
          type="button"
        >
          {mutation.isPending ? (
            <Loader2 className="mr-1 size-4 animate-spin" />
          ) : (
            <Rocket className="mr-1 size-4" />
          )}
          {`${isRedeploy ? 'Redeploy' : 'Deploy'} ${
            selected?.label ?? selected?.sha.slice(0, 7) ?? ''
          } to ${env?.name ?? envSlug}`}
        </Button>
      </div>
    </div>
  )
}

function BranchPicker({
  activeBranch,
  branches,
  branchesLoading,
  commits,
  commitsLoading,
  current,
  onBranchSelect,
  onCommitSelect,
  onQueryChange,
  query,
  selectedSha,
}: {
  activeBranch: null | string
  branches: DeploymentRef[]
  branchesLoading: boolean
  commits: DeploymentCommit[]
  commitsLoading: boolean
  current: null | string
  onBranchSelect: (name: string) => void
  onCommitSelect: (commit: DeploymentCommit) => void
  onQueryChange: (q: string) => void
  query: string
  selectedSha: null | string
}) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <div className="flex flex-col gap-2">
        <input
          aria-label="Filter branches"
          className="border-secondary placeholder:text-tertiary focus:border-action rounded-md border bg-transparent px-2 py-1 text-sm focus:outline-none"
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter branches…"
          type="text"
          value={query}
        />
        {branchesLoading ? (
          <LoadingState label="Loading branches…" />
        ) : branches.length === 0 ? (
          <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
            No branches.
          </p>
        ) : (
          <ul className="border-secondary max-h-65 overflow-y-auto rounded-md border">
            {branches.map((b) => {
              const active = b.name === activeBranch
              return (
                <li
                  className={cn(
                    'border-b border-tertiary last:border-b-0',
                    active && 'bg-action/5',
                  )}
                  key={b.name}
                >
                  <button
                    className="flex w-full min-w-0 items-center gap-2 px-3 py-2 text-left"
                    onClick={() => onBranchSelect(b.name)}
                    type="button"
                  >
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {b.name}
                    </span>
                    {b.pr_number ? (
                      <Badge variant="outline">#{b.pr_number}</Badge>
                    ) : null}
                    {active ? <Check className="text-action size-4" /> : null}
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </div>
      <div>
        {!activeBranch ? (
          <p className="border-secondary text-tertiary rounded-md border border-dashed p-3 text-sm">
            Select a branch to see commits.
          </p>
        ) : (
          <CommitList
            commits={commits}
            current={current}
            isLoading={commitsLoading}
            onSelect={onCommitSelect}
            selectedSha={selectedSha}
          />
        )}
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
      <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
        No commits available.
      </p>
    )
  return (
    <ul className="border-secondary max-h-65 overflow-y-auto rounded-md border">
      {commits.map((c) => {
        const active = c.sha === selectedSha
        const isCurrent = current ? c.sha.startsWith(current) : false
        return (
          <li
            className={cn(
              'flex min-w-0 items-center gap-3 border-b border-tertiary px-3 py-2 last:border-b-0',
              active && 'bg-action/5',
            )}
            key={c.sha}
          >
            <button
              className="flex min-w-0 flex-1 items-center gap-3 text-left"
              onClick={() => onSelect(c)}
              type="button"
            >
              <span className="shrink-0 font-mono text-xs">{c.short_sha}</span>
              <span className="min-w-0 flex-1 truncate text-sm">
                {c.message}
              </span>
              <span className="text-tertiary shrink-0 text-xs">{c.author}</span>
              {c.is_head ? <Badge variant="outline">HEAD</Badge> : null}
              {isCurrent ? <Badge variant="neutral">current</Badge> : null}
              {active ? <Check className="text-action size-4" /> : null}
            </button>
            {c.url ? (
              <a
                aria-label="View commit on GitHub"
                className="text-tertiary hover:text-primary"
                href={c.url}
                rel="noopener"
                target="_blank"
              >
                <ExternalLink className="size-3.5" />
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
      <p className="text-tertiary text-xs">
        Re-deploying — no commit delta to summarize.
      </p>
    )
  if (isLoading || !data) return null
  return (
    <div className="border-secondary bg-tertiary/20 rounded-md border p-3 text-xs">
      <div className="text-tertiary font-mono">
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

function PickerToggle({
  defaultLabel,
  mode,
  onChange,
}: {
  defaultLabel: string
  mode: 'branches' | 'default'
  onChange: (mode: 'branches' | 'default') => void
}) {
  return (
    <div
      className="border-secondary inline-flex rounded-md border text-xs"
      role="group"
    >
      <button
        aria-pressed={mode === 'default'}
        className={cn(
          'px-2 py-1',
          mode === 'default'
            ? 'bg-action/10 text-primary'
            : 'text-tertiary hover:bg-tertiary/30',
        )}
        onClick={() => onChange('default')}
        type="button"
      >
        {defaultLabel}
      </button>
      <button
        aria-pressed={mode === 'branches'}
        className={cn(
          'border-l border-secondary px-2 py-1',
          mode === 'branches'
            ? 'bg-action/10 text-primary'
            : 'text-tertiary hover:bg-tertiary/30',
        )}
        onClick={() => onChange('branches')}
        type="button"
      >
        Branches
      </button>
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
      <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
        No tags available.
      </p>
    )
  return (
    <ul className="border-secondary max-h-65 overflow-y-auto rounded-md border">
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
              <span className="text-tertiary font-mono text-xs">
                {t.sha.slice(0, 7)}
              </span>
              {isCurrent ? <Badge variant="neutral">current</Badge> : null}
              {active ? <Check className="text-action size-4" /> : null}
            </button>
          </li>
        )
      })}
    </ul>
  )
}
