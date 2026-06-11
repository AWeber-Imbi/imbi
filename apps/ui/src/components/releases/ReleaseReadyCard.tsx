import { useEffect, useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import { Check, Loader2, RefreshCw, Rocket, Sparkles, Tag } from 'lucide-react'

import { draftReleaseNotes } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SkText } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { SEMVER_RE } from '@/lib/semver'
import type {
  DraftReleaseNotesResponse,
  ReleaseDrift,
  SemverBump,
} from '@/types'

import { ReleaseCommitPicker } from './ReleaseCommitPicker'
import { useCutReleaseMutation } from './useCutReleaseMutation'

interface ReleaseReadyCardProps {
  drift: ReleaseDrift
  onCut: () => void
  orgSlug: string
  projectId: string
}

interface TagFieldsProps {
  latestTag: null | string
  onChange: (value: string) => void
  tag: string
  tagValid: boolean
}

// fallow-ignore-next-line complexity
export function ReleaseReadyCard({
  drift,
  onCut,
  orgSlug,
  projectId,
}: ReleaseReadyCardProps) {
  const commits = drift.commits
  const [selectedSha, setSelectedSha] = useState<null | string>(
    commits[0]?.sha ?? null,
  )
  const [tag, setTag] = useState<string>(drift.suggested_tag)
  const [notes, setNotes] = useState<string>('')
  const [tagDirty, setTagDirty] = useState(false)
  const [notesDirty, setNotesDirty] = useState(false)
  // What the AI draft actually proposed, once it has run. Drives the hint
  // line so it reflects the real draft rather than the server's keyword
  // heuristic (drift.suggested_*), which can disagree.
  const [aiSuggestion, setAiSuggestion] = useState<null | {
    bump: SemverBump
    version: string
  }>(null)

  // AI drafting needs a base tag to compare against; for the first-ever
  // release there's nothing to diff, so notes are authored by hand.
  const canDraft = !!drift.latest_tag_sha && !!selectedSha
  const draftMutation = useMutation({
    mutationFn: ({ headSha }: { headSha: string }) =>
      draftReleaseNotes(orgSlug, projectId, {
        base_sha: drift.latest_tag_sha ?? '',
        head_sha: headSha,
        last_tag: drift.latest_tag,
      }),
  })
  const seedFromDraft = (data: DraftReleaseNotesResponse) => {
    setAiSuggestion({ bump: data.bump, version: data.version })
    if (!tagDirty) setTag(data.version)
    if (!notesDirty) setNotes(data.notes_markdown)
  }

  // Auto-draft once on mount when a diff against the prior tag exists.
  useEffect(() => {
    if (!canDraft || !selectedSha) return
    draftMutation.mutate({ headSha: selectedSha }, { onSuccess: seedFromDraft })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const { cut, isPending } = useCutReleaseMutation({
    onSuccess: onCut,
    orgSlug,
    projectId,
  })

  // Up to date — nothing new to cut.
  if (commits.length === 0) {
    return (
      <div className="border-success bg-success/10 flex items-center gap-3 rounded-lg border p-4">
        <span className="text-success">
          <Check size={18} strokeWidth={3} />
        </span>
        <div>
          <div className="text-sm font-semibold">Up to date</div>
          <div className="text-tertiary mt-0.5 text-xs">
            The latest commit is already released — nothing new to cut.
          </div>
        </div>
      </div>
    )
  }

  const tagValid = SEMVER_RE.test(tag)
  const isDrafting = draftMutation.isPending
  const canSubmit = tagValid && !!selectedSha && !isPending && !isDrafting
  const reset = () => {
    setSelectedSha(commits[0]?.sha ?? null)
    setTag(drift.suggested_tag)
    setNotes('')
    setTagDirty(false)
    setNotesDirty(false)
    setAiSuggestion(null)
  }
  const submit = () => {
    if (!selectedSha) return
    cut({
      committish: selectedSha,
      release_name: tag,
      release_notes_markdown: notes,
      tag,
    })
  }

  return (
    <div className="border-action overflow-hidden rounded-lg border">
      <div className="border-action bg-action/10 flex items-center gap-3 border-b px-4 py-3">
        <span className="border-action bg-primary text-action flex size-8 shrink-0 items-center justify-center rounded-md border">
          <Tag size={16} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">
            {drift.commits_since_tag} commit
            {drift.commits_since_tag === 1 ? '' : 's'} ready to release
          </div>
          <div className="text-action mt-0.5 text-xs">
            Build at{' '}
            <span className="font-mono">
              {drift.head_sha?.slice(0, 7) ?? '—'}
            </span>{' '}
            · cutting{' '}
            <span className="font-mono">{tag || drift.suggested_tag}</span>
          </div>
        </div>
      </div>

      <div className="flex flex-col gap-4 px-4 py-4">
        <section>
          <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
            Select the newest commit to include
          </p>
          <ReleaseCommitPicker
            commits={commits}
            onSelect={setSelectedSha}
            selectedSha={selectedSha}
          />
        </section>

        <section className="border-tertiary flex flex-col gap-2 border-t pt-4">
          <p className="text-tertiary text-xs tracking-wider uppercase">
            Tag & release notes
          </p>
          <TagFields
            latestTag={drift.latest_tag}
            onChange={(v) => {
              setTag(v)
              setTagDirty(true)
            }}
            tag={tag}
            tagValid={tagValid}
          />
          {!tagValid && tag.length > 0 ? (
            <span className="text-danger text-xs">
              Use a semver tag, e.g. v6.5.2
            </span>
          ) : null}
          {canDraft ? (
            <div className="flex items-center justify-between">
              <span className="text-tertiary text-xs">
                {aiSuggestion
                  ? `AI suggests a ${aiSuggestion.bump} bump → `
                  : drift.suggested_bump
                    ? `Suggested ${drift.suggested_bump} bump → `
                    : ''}
                <span className="font-mono">
                  {aiSuggestion?.version ?? drift.suggested_tag}
                </span>
              </span>
              <Button
                disabled={!selectedSha || draftMutation.isPending}
                onClick={() => {
                  if (!selectedSha) return
                  draftMutation.mutate(
                    { headSha: selectedSha },
                    {
                      onSuccess: (data) => {
                        setAiSuggestion({
                          bump: data.bump,
                          version: data.version,
                        })
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
          ) : null}
          {isDrafting && !notes ? (
            <DraftingNotes />
          ) : (
            <Textarea
              className="min-h-40 font-mono text-xs"
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
          <Button disabled={!canSubmit} onClick={submit} type="button">
            {isPending ? (
              <Loader2 className="mr-1 size-4 animate-spin" />
            ) : (
              <Rocket className="mr-1 size-4" />
            )}
            {`Tag ${tag || 'vX.Y.Z'} & release`}
          </Button>
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
    <div className="border-amber-border min-h-40 rounded-md border border-dashed p-3">
      <div className="text-amber-text mb-2 flex items-center gap-1.5 text-xs">
        <Sparkles className="size-3" />
        Imbot is drafting release notes…
      </div>
      <SkText ai widths={['96%', '88%', '92%', '70%']} />
    </div>
  )
}

// The current/new tag input pair mirrors the deploy PromoteTab's; kept as a
// small local component rather than shared to avoid coupling the two flows.
// fallow-ignore-next-line duplication
function TagFields({ latestTag, onChange, tag, tagValid }: TagFieldsProps) {
  return (
    <div className="grid grid-cols-2 gap-3">
      <Label className="text-tertiary flex flex-col gap-1 text-xs">
        Current
        <Input
          className="bg-tertiary font-mono"
          disabled
          value={latestTag ?? '—'}
        />
      </Label>
      <Label className="text-tertiary flex flex-col gap-1 text-xs">
        New tag
        <Input
          aria-invalid={!tagValid && tag.length > 0}
          className="font-mono"
          onChange={(e) => onChange(e.target.value)}
          placeholder="vX.Y.Z"
          value={tag}
        />
      </Label>
    </div>
  )
}
