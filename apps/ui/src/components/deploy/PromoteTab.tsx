import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw, Rocket, Sparkles } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  compareDeploymentRefs,
  draftReleaseNotes,
  listCurrentReleases,
  promoteDeployment,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'
import { cn } from '@/lib/utils'
import type { DraftReleaseNotesResponse, Environment } from '@/types'

interface PromoteTabProps {
  environments: Environment[]
  fromCommittish?: null | string
  fromEnvironment: string
  onClose: () => void
  onRunStarted?: (run: import('./DeploymentModal').DeploymentRunStarted) => void
  open: boolean
  orgSlug: string
  projectId: string
  toEnvironment: string
}

const SEMVER_RE = /^v?\d+\.\d+\.\d+(?:[-+].+)?$/

export function PromoteTab({
  environments,
  fromCommittish,
  fromEnvironment,
  onClose,
  onRunStarted,
  open,
  orgSlug,
  projectId,
  toEnvironment,
}: PromoteTabProps) {
  const toEnvName = useMemo(
    () =>
      environments.find((e) => e.slug === toEnvironment)?.name ?? toEnvironment,
    [environments, toEnvironment],
  )
  const { data: currentReleases = [] } = useQuery({
    enabled: open && !!orgSlug && !!projectId,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, projectId, signal),
    queryKey: ['currentReleases', orgSlug, projectId],
  })

  const fromCurrent = useMemo(() => {
    return currentReleases.find((r) => r.environment.slug === fromEnvironment)
  }, [currentReleases, fromEnvironment])
  const toCurrent = useMemo(() => {
    return currentReleases.find((r) => r.environment.slug === toEnvironment)
  }, [currentReleases, toEnvironment])

  const lastTag = toCurrent?.release?.version ?? null
  const fromTipSha = fromCommittish ?? fromCurrent?.release?.version ?? null

  // Compare last_tag → fromTipSha to enumerate the commits in flight.
  const compareEnabled =
    open && !!lastTag && !!fromTipSha && lastTag !== fromTipSha
  const { data: compare, isLoading: compareLoading } = useQuery({
    enabled: compareEnabled,
    queryFn: ({ signal }) =>
      compareDeploymentRefs(
        orgSlug,
        projectId,
        lastTag ?? '',
        fromTipSha ?? '',
        undefined,
        signal,
      ),
    queryKey: ['compare', orgSlug, projectId, lastTag, fromTipSha],
  })
  const commits = compare?.commits ?? []

  // The selected build is the SHA we'll cut the tag at.  Default to
  // the tip; user can pick an earlier commit in the list.
  const [selectedSha, setSelectedSha] = useState<null | string>(null)
  useEffect(() => {
    if (commits.length > 0) {
      const tip = commits[commits.length - 1]
      setSelectedSha(tip.sha)
    } else {
      setSelectedSha(fromTipSha)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [compare, fromTipSha])

  // AI suggestion + draft notes — fetched on demand and on regenerate.
  const draftMutation = useMutation({
    mutationFn: ({ headSha }: { headSha: string }) =>
      draftReleaseNotes(orgSlug, projectId, {
        base_sha: lastTag ?? '',
        head_sha: headSha,
        last_tag: lastTag,
      }),
  })
  const [draft, setDraft] = useState<DraftReleaseNotesResponse | null>(null)

  // Auto-draft on first open when we have a base + head.
  useEffect(() => {
    if (!open || draft || !lastTag || !selectedSha) return
    draftMutation.mutate({ headSha: selectedSha }, { onSuccess: setDraft })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, lastTag, selectedSha])

  const [tag, setTag] = useState<string>('')
  const [notes, setNotes] = useState<string>('')
  const [tagDirty, setTagDirty] = useState(false)
  const [notesDirty, setNotesDirty] = useState(false)

  // When a draft arrives, seed tag + notes from it (unless the user
  // has already edited them).
  useEffect(() => {
    if (!draft) return
    if (!tagDirty) setTag(draft.version)
    if (!notesDirty) setNotes(draft.notes_markdown)
  }, [draft, tagDirty, notesDirty])

  const queryClient = useQueryClient()
  const promoteMutation = useMutation({
    mutationFn: () =>
      promoteDeployment(orgSlug, projectId, {
        action: 'promote',
        from_committish: selectedSha ?? '',
        from_environment: fromEnvironment,
        prerelease: false,
        release_name: tag,
        release_notes_markdown: notes,
        tag,
        to_environment: toEnvironment,
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
      void queryClient.invalidateQueries({
        queryKey: ['promotionOptions', orgSlug, projectId],
      })
      const releaseUrl = data.release_url
      const runUrl = data.run.run_url
      const tagLabel = data.tag ?? tag
      // Prefer the run URL when present; fall back to the release URL
      // so the watcher's recreated toast still has a useful action.
      const actionUrl = runUrl ?? releaseUrl
      const actionLabel = runUrl
        ? 'View run'
        : releaseUrl
          ? 'View release'
          : undefined
      if (onRunStarted && data.run.run_id) {
        const toastId = toast.loading(
          `Promoting ${tagLabel} to ${toEnvName}…`,
          {
            action:
              actionUrl && actionLabel
                ? {
                    label: actionLabel,
                    onClick: () => window.open(actionUrl, '_blank', 'noopener'),
                  }
                : undefined,
            description: data.run.status
              ? `status: ${data.run.status}`
              : undefined,
            icon: <Loader2 className="h-4 w-4 animate-spin" />,
          },
        )
        onRunStarted({
          actionLabel,
          actionUrl,
          envName: toEnvName,
          initialStatus: data.run.status,
          originOrgSlug: orgSlug,
          originProjectId: projectId,
          runId: data.run.run_id,
          runUrl,
          toastId,
        })
      } else {
        const url = releaseUrl ?? runUrl
        toast.success(
          `Promoted ${tagLabel} to ${toEnvName}`,
          url
            ? {
                action: {
                  label: 'View',
                  onClick: () => window.open(url, '_blank', 'noopener'),
                },
              }
            : undefined,
        )
      }
      onClose()
    },
  })

  const tagValid = SEMVER_RE.test(tag)
  const canPromote = tagValid && !!selectedSha && !promoteMutation.isPending

  return (
    <div className="flex flex-col gap-4">
      <header className="bg-tertiary/20 rounded-md border border-secondary px-3 py-2 text-xs">
        <span className="text-tertiary">Promoting </span>
        <span className="font-medium">{fromEnvironment}</span>
        <span className="text-tertiary"> → </span>
        <span className="font-medium">{toEnvironment}</span>
        {lastTag ? (
          <>
            <span className="text-tertiary"> · last tag </span>
            <span className="font-mono">{lastTag}</span>
          </>
        ) : (
          <span className="text-tertiary"> · no prior release</span>
        )}
      </header>

      {/* Step 1 — pick the build */}
      <section>
        <p className="mb-2 text-xs uppercase tracking-wider text-tertiary">
          Step 1 — Build to promote
        </p>
        {compareEnabled && compareLoading ? (
          <LoadingState label="Loading commits…" />
        ) : !compareEnabled ? (
          <p className="rounded-md border border-secondary p-3 text-sm text-tertiary">
            {!lastTag
              ? 'No prior release to compare against.'
              : 'No commit delta to compare for this selection.'}
          </p>
        ) : commits.length === 0 ? (
          <p className="rounded-md border border-secondary p-3 text-sm text-tertiary">
            No new commits between <span className="font-mono">{lastTag}</span>{' '}
            and <span className="font-mono">{fromEnvironment}</span>.
          </p>
        ) : (
          <ul className="max-h-[200px] overflow-y-auto rounded-md border border-secondary">
            {[...commits].reverse().map((c, idx) => {
              const tipIndex = idx === 0 ? 'tip' : `−${idx}`
              const active = c.sha === selectedSha
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
                    onClick={() => setSelectedSha(c.sha)}
                    type="button"
                  >
                    <span className="shrink-0 font-mono text-xs">
                      {c.short_sha}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {c.message}
                    </span>
                    <Badge variant="neutral">{tipIndex}</Badge>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </section>

      {/* Step 2 — version + notes */}
      <section>
        <p className="mb-2 text-xs uppercase tracking-wider text-tertiary">
          Step 2 — Tag & release notes
        </p>
        <div className="grid grid-cols-[160px_160px_1fr] gap-3">
          <label className="flex flex-col gap-1 text-xs text-tertiary">
            Current
            <Input className="font-mono" disabled value={lastTag ?? ''} />
          </label>
          <label className="flex flex-col gap-1 text-xs text-tertiary">
            New tag
            <Input
              aria-invalid={!tagValid && tag.length > 0}
              className="font-mono"
              onChange={(e) => {
                setTag(e.target.value)
                setTagDirty(true)
              }}
              placeholder="vX.Y.Z"
              value={tag}
            />
          </label>
          <div className="flex flex-col gap-1 text-xs">
            <span className="text-tertiary">AI suggestion</span>
            <div className="bg-accent/10 flex min-h-[40px] items-start gap-2 rounded-md border border-accent p-2 text-accent">
              <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              {draftMutation.isPending && !draft ? (
                <span className="text-tertiary">drafting…</span>
              ) : draft ? (
                <span>
                  Bump <span className="font-medium">{draft.bump}</span> →{' '}
                  <span className="font-mono">{draft.version}</span>.{' '}
                  {draft.reasoning}
                  {draft.degraded ? (
                    <span className="text-tertiary"> (AI unavailable)</span>
                  ) : null}
                </span>
              ) : (
                <span className="text-tertiary">
                  No draft yet — pick a build above.
                </span>
              )}
            </div>
          </div>
        </div>

        <div className="mt-3 flex items-center justify-between">
          <span className="text-xs text-tertiary">
            {compare?.commits?.length ?? 0} commits considered
          </span>
          <Button
            disabled={!selectedSha || draftMutation.isPending}
            onClick={() => {
              if (!selectedSha) return
              draftMutation.mutate(
                { headSha: selectedSha },
                {
                  onSuccess: (data) => {
                    setDraft(data)
                    setNotesDirty(false)
                    setTagDirty(false)
                  },
                },
              )
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            <RefreshCw
              className={cn(
                'mr-1 h-3.5 w-3.5',
                draftMutation.isPending && 'animate-spin',
              )}
            />
            Regenerate with AI
          </Button>
        </div>

        <Textarea
          className="mt-2 min-h-[160px] font-mono text-xs"
          onChange={(e) => {
            setNotes(e.target.value)
            setNotesDirty(true)
          }}
          placeholder="## Highlights&#10;- …"
          value={notes}
        />
      </section>

      {/* Footer */}
      <p className="text-xs text-tertiary">
        On promote, a release{' '}
        <span className="font-mono">{tag || 'vX.Y.Z'}</span> will be created at{' '}
        <span className="font-mono">{selectedSha?.slice(0, 7) ?? '—'}</span> and
        rolled out to {toEnvironment}.
      </p>
      <div className="bg-secondary/30 -mx-6 -mb-4 mt-2 flex items-center justify-end gap-2 border-t border-tertiary px-6 py-4">
        <Button onClick={onClose} type="button" variant="ghost">
          Cancel
        </Button>
        <Button
          disabled={!canPromote}
          onClick={() => promoteMutation.mutate()}
          type="button"
        >
          {promoteMutation.isPending ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Rocket className="mr-1 h-4 w-4" />
          )}
          {`Tag ${tag || 'vX.Y.Z'} & deploy to ${toEnvironment}`}
        </Button>
      </div>
    </div>
  )
}
