import { useEffect, useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import {
  ArrowUp,
  Check,
  Loader2,
  RefreshCw,
  Rocket,
  Sparkles,
} from 'lucide-react'

import { draftReleaseNotes } from '@/api/endpoints'
import { ReleaseCommitPicker } from '@/components/releases/ReleaseCommitPicker'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SkText } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import type { ChipColors } from '@/lib/chip-colors'
import { SEMVER_RE } from '@/lib/semver'
import type { DraftReleaseNotesResponse } from '@/types'

import type { PipelineStage } from './pipeline'
import { StageCardShell } from './StageCardShell'
import type { DeploymentActions } from './useDeploymentActions'

interface PendingPromoteCardProps {
  accent: ChipColors | null
  actions: DeploymentActions
  canTrigger: boolean
  orgSlug: string
  projectId: string
  stage: PipelineStage
}

/**
 * Always-on inline promote form: the upstream environment runs untagged
 * commits, so moving them here cuts a new tag and rolls it out. Pick the
 * newest commit to include, set the tag + notes (AI-drafted), promote.
 * The commit range comes from imbi's synced history (stage.pendingCommits).
 */
// fallow-ignore-next-line complexity
export function PendingPromoteCard({
  accent,
  actions,
  canTrigger,
  orgSlug,
  projectId,
  stage,
}: PendingPromoteCardProps) {
  const upstreamName = stage.upstream?.name ?? 'upstream'
  const lastTag = stage.current?.release?.tag ?? null
  const fromTipSha = stage.upstreamCurrent?.release?.committish ?? null
  // Already newest-first from the synced ClickHouse history.
  const commits = stage.pendingCommits

  const [selectedSha, setSelectedSha] = useState<null | string>(null)
  useEffect(() => {
    setSelectedSha(commits.length > 0 ? commits[0].sha : fromTipSha)
  }, [commits, fromTipSha])

  const [tag, setTag] = useState('')
  const [notes, setNotes] = useState('')
  const [tagDirty, setTagDirty] = useState(false)
  const [notesDirty, setNotesDirty] = useState(false)
  const [draft, setDraft] = useState<DraftReleaseNotesResponse | null>(null)

  const draftMutation = useMutation({
    mutationFn: ({ headSha }: { headSha: string }) =>
      draftReleaseNotes(orgSlug, projectId, {
        base_sha: lastTag ?? '',
        head_sha: headSha,
        last_tag: lastTag,
      }),
  })

  // Auto-draft once when there is a non-empty diff to summarize.
  const hasDiff = !!lastTag && !!selectedSha && commits.length > 0
  useEffect(() => {
    if (draft || !hasDiff) return
    draftMutation.mutate(
      { headSha: selectedSha as string },
      { onSuccess: setDraft },
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasDiff, selectedSha])

  useEffect(() => {
    if (!draft) return
    if (!tagDirty) setTag(draft.version)
    if (!notesDirty) setNotes(draft.notes_markdown)
  }, [draft, tagDirty, notesDirty])

  if (!fromTipSha) {
    return (
      <div className="border-tertiary text-tertiary rounded-lg border p-4 text-sm">
        Nothing is deployed in {upstreamName} yet — deploy upstream first.
      </div>
    )
  }

  // Synced: nothing newer than this env's release is deployed upstream.
  if (lastTag && commits.length === 0) {
    return <UpToDateCard upstreamName={upstreamName} />
  }

  const tagValid = SEMVER_RE.test(tag)
  const isDrafting = draftMutation.isPending
  const canSubmit =
    tagValid &&
    !!selectedSha &&
    canTrigger &&
    !actions.promotePending &&
    !isDrafting
  const selIdx = commits.findIndex((c) => c.sha === selectedSha)
  const heldCount = selIdx > 0 ? selIdx : 0
  const reset = () => {
    setSelectedSha(commits.length > 0 ? commits[0].sha : fromTipSha)
    setTag(draft?.version ?? '')
    setNotes(draft?.notes_markdown ?? '')
    setTagDirty(false)
    setNotesDirty(false)
  }

  return (
    <StageCardShell
      accent={accent}
      icon={ArrowUp}
      subtitle={
        <>
          Promoting cuts a new tag from {upstreamName} and deploys it to{' '}
          {stage.env.name.toLowerCase()}
        </>
      }
      title={
        commits.length > 0
          ? `${commits.length} commit${commits.length === 1 ? '' : 's'} waiting to promote from ${upstreamName}`
          : `Promote from ${upstreamName}`
      }
    >
      <div className="flex flex-col gap-4 px-4 py-4">
        {commits.length > 0 ? (
          <div className="text-tertiary flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-xs">
            <span>{commits.length} commits</span>
            <span className="ml-auto">
              {lastTag ?? '—'} … {fromTipSha.slice(0, 7)}
            </span>
          </div>
        ) : null}

        <section>
          <div className="mb-2 flex items-center justify-between gap-3">
            <p className="text-tertiary text-xs tracking-wider uppercase">
              Select the newest commit to include
            </p>
            {heldCount > 0 ? (
              <span className="text-tertiary text-xs">
                {heldCount} newer held back
              </span>
            ) : null}
          </div>
          {commits.length === 0 ? (
            <p className="border-secondary text-tertiary rounded-md border p-3 text-sm">
              {`No prior release to compare against — promoting tags ${upstreamName}'s current commit.`}
            </p>
          ) : (
            <ReleaseCommitPicker
              accent={accent}
              commits={commits}
              onSelect={setSelectedSha}
              selectedSha={selectedSha}
            />
          )}
        </section>

        <section className="border-tertiary flex flex-col gap-2 border-t pt-4">
          <p className="text-tertiary text-xs tracking-wider uppercase">
            Tag & release notes
          </p>
          <div className="grid grid-cols-2 gap-3">
            <Label className="text-tertiary flex flex-col gap-1 text-xs">
              Current
              <Input
                className="bg-tertiary font-mono"
                disabled
                value={lastTag ?? '—'}
              />
            </Label>
            <Label className="text-tertiary flex flex-col gap-1 text-xs">
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
            </Label>
          </div>
          {!tagValid && tag.length > 0 ? (
            <span className="text-danger text-xs">
              Use a semver tag, e.g. v6.5.2
            </span>
          ) : null}
          <div className="flex items-center justify-between gap-3">
            <span className="text-tertiary min-w-0 truncate text-xs">
              {draftMutation.isPending && !draft ? (
                'AI drafting…'
              ) : draft ? (
                <>
                  AI suggests a {draft.bump} bump →{' '}
                  <span className="font-mono">{draft.version}</span>
                  {draft.degraded ? ' (AI unavailable)' : ''}
                </>
              ) : (
                `${commits.length} commits considered`
              )}
            </span>
            <Button
              disabled={!hasDiff || draftMutation.isPending}
              onClick={() => {
                if (!hasDiff) return
                draftMutation.mutate(
                  { headSha: selectedSha as string },
                  {
                    onSuccess: (data) => {
                      setDraft(data)
                      setTagDirty(false)
                      setNotesDirty(false)
                      setTag(data.version)
                      setNotes(data.notes_markdown)
                    },
                  },
                )
              }}
              size="sm"
              type="button"
              variant="outline"
            >
              {draftMutation.isPending ? (
                <RefreshCw className="mr-1 size-3.5 animate-spin" />
              ) : (
                <Sparkles className="mr-1 size-3.5" />
              )}
              Regenerate with AI
            </Button>
          </div>
          {isDrafting && !draft ? (
            <DraftingNotes />
          ) : (
            <Textarea
              className="min-h-32 font-mono text-xs"
              onChange={(e) => {
                setNotes(e.target.value)
                setNotesDirty(true)
              }}
              placeholder="## Highlights&#10;- …"
              value={notes}
            />
          )}
        </section>

        <div className="border-tertiary flex items-center justify-end gap-2 border-t pt-4">
          <Button onClick={reset} type="button" variant="ghost">
            Reset
          </Button>
          <Button
            disabled={!canSubmit}
            onClick={() => {
              if (!selectedSha) return
              actions.promote({
                fromEnvironment: stage.upstream?.slug ?? '',
                notes,
                sha: selectedSha,
                tag,
                toEnvironment: stage.env.slug,
                toEnvName: stage.env.name,
              })
            }}
            type="button"
          >
            {actions.promotePending ? (
              <Loader2 className="mr-1 size-4 animate-spin" />
            ) : (
              <Rocket className="mr-1 size-4" />
            )}
            {`Tag ${tag || 'vX.Y.Z'} & deploy to ${stage.env.name.toLowerCase()}`}
          </Button>
        </div>
      </div>
    </StageCardShell>
  )
}

export function UpToDateCard({ upstreamName }: { upstreamName: string }) {
  return (
    <div className="border-success bg-success/10 flex items-center gap-3 rounded-lg border p-4">
      <span className="text-success">
        <Check size={18} strokeWidth={3} />
      </span>
      <div>
        <div className="text-sm font-semibold">
          Up to date with {upstreamName}
        </div>
        <div className="text-tertiary mt-0.5 text-xs">
          Nothing is waiting to move into this environment.
        </div>
      </div>
    </div>
  )
}

/**
 * Amber "Imbot is drafting" placeholder shown in the notes region while the
 * release-notes draft is generating, before the textarea is seeded.
 */
function DraftingNotes() {
  return (
    <div className="border-amber-border min-h-32 rounded-md border border-dashed p-3">
      <div className="text-amber-text mb-2 flex items-center gap-1.5 text-xs">
        <Sparkles className="size-3" />
        Imbot is drafting release notes…
      </div>
      <SkText ai widths={['96%', '88%', '92%', '70%']} />
    </div>
  )
}
