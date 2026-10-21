/* eslint-disable react-refresh/only-export-components */
import { ApiError } from '@/api/client'
import { Alert } from '@/components/ui/alert'
import { Checkbox } from '@/components/ui/checkbox'
import type { BreakingChange } from '@/types'

/** The flows the API gates, in the tense the copy needs. */
const ACTION_COPY = {
  promote: { gerund: 'Promoting', verb: 'Promote' },
  release: { gerund: 'Releasing', verb: 'Release' },
} as const

export type BreakingChangeAction = keyof typeof ACTION_COPY

/** What a form shows and requires, from its draft and any refusal. */
export interface BreakingGate {
  changes: BreakingChange[]
  lastTag: null | string
  needsAck: boolean
}

/**
 * The API's 409 for a non-breaking tag over commits marked breaking:
 * `detail` on the `breaking_changes_unacknowledged` refusal.
 */
export interface BreakingRefusal {
  /** The declared breaking commits the server found. */
  breaking_changes: BreakingChange[]
  bump: 'major' | 'minor'
  /** The release the server measured `tag` against. */
  last_tag: string
  message: string
  tag: string
}

interface BreakingChangeNoticeProps {
  acknowledged: boolean
  /** What the operator is about to do, for the confirmation copy. */
  action: BreakingChangeAction
  /**
   * The release-notes draft's, plus any an API refusal named; nothing
   * renders until one of them has.
   */
  breakingChanges: BreakingChange[] | undefined
  /** The release the new tag is bumped from. */
  lastTag: null | string
  onAcknowledgedChange: (next: boolean) => void
  /**
   * Ask for the acknowledgement whatever the tags say: the API refused
   * this tag (see {@link resolveBreakingGate}).
   */
  required?: boolean
  /** The tag about to be cut. */
  tag: string
}

/**
 * The breaking changes the release-notes draft found, shown above the tag
 * they bear on. Renders nothing when there are none.
 *
 * A warning while the tag is a breaking-change bump — the evidence for the
 * version an operator is about to ship. Once the tag is edited down to one
 * that hides them, a danger strip with an acknowledgement checkbox, in the
 * same shape as {@link CiFailureNotice}: shipping it is still the
 * operator's call, but it is recorded against the release.
 *
 * The API only refuses the commits their authors marked breaking (it can
 * re-derive those); the rest are the model's judgment, so this checkbox is
 * what holds them to the same bar. When the API refuses anyway, the form
 * passes its answer through {@link resolveBreakingGate} and `required`.
 */
export function BreakingChangeNotice({
  acknowledged,
  action,
  breakingChanges,
  lastTag,
  onAcknowledgedChange,
  required = false,
  tag,
}: BreakingChangeNoticeProps) {
  const changes = breakingChanges ?? []
  if (changes.length === 0) return null
  const needsAck =
    required || breakingNeedsAcknowledgement(changes, lastTag, tag)
  const { gerund, verb } = ACTION_COPY[action]
  const count = `${changes.length} breaking change${changes.length === 1 ? '' : 's'}`
  return (
    <Alert
      title={
        needsAck
          ? `${tag} is not a breaking-change release`
          : `${count} in this release`
      }
      variant={needsAck ? 'danger' : 'warning'}
    >
      <div className="flex flex-col gap-2">
        <ul className="flex flex-col gap-1">
          {changes.map((change) => (
            <li
              className="flex min-w-0 items-baseline gap-2"
              key={change.commit}
            >
              {change.url ? (
                <a
                  className="shrink-0 font-mono text-xs underline"
                  href={change.url}
                  rel="noopener noreferrer"
                  target="_blank"
                >
                  {change.commit}
                </a>
              ) : (
                <span className="shrink-0 font-mono text-xs">
                  {change.commit}
                </span>
              )}
              <span className="min-w-0">
                {change.description}
                {change.declared ? (
                  <span className="opacity-80">
                    {' '}
                    · marked breaking by its author
                  </span>
                ) : null}
              </span>
            </li>
          ))}
        </ul>
        {needsAck ? (
          <>
            <span>
              Consumers upgrading from {lastTag} to {tag} will not expect{' '}
              {changes.length === 1 ? 'this change' : 'these changes'}. Release
              a {breakingBump(lastTag)} version instead, or confirm they are not
              breaking — {gerund} anyway will be recorded against the release.
            </span>
            <label className="flex w-fit cursor-pointer items-center gap-2 text-xs font-medium">
              <Checkbox
                aria-label={`${verb} ${tag} anyway despite the breaking changes`}
                checked={acknowledged}
                onCheckedChange={(checked) =>
                  onAcknowledgedChange(checked === true)
                }
              />
              {verb} as {tag} anyway
            </label>
          </>
        ) : null}
      </div>
    </Alert>
  )
}

/**
 * Whether shipping `tag` over `changes` needs an acknowledgement: there is
 * at least one, and `tag` is a newer release that does not bump the
 * version a breaking change belongs in.
 */
export function breakingNeedsAcknowledgement(
  changes: BreakingChange[] | undefined,
  lastTag: null | string,
  tag: string,
): boolean {
  return (
    (changes?.length ?? 0) > 0 && !!lastTag && skipsBreakingBump(lastTag, tag)
  )
}

/**
 * The refusal carried by a promote or cut error, or `null` for any other
 * error.
 */
export function breakingRefusal(error: unknown): BreakingRefusal | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null
  const detail = (error.data as undefined | { detail?: unknown })?.detail
  if (!detail || typeof detail !== 'object') return null
  const refusal = detail as Partial<BreakingRefusal> & { error?: unknown }
  if (
    refusal.error !== 'breaking_changes_unacknowledged' ||
    !Array.isArray(refusal.breaking_changes) ||
    typeof refusal.tag !== 'string' ||
    typeof refusal.last_tag !== 'string'
  ) {
    return null
  }
  return refusal as BreakingRefusal
}

/**
 * What a form shows, and whether it must hold submit for the
 * acknowledgement.
 *
 * The draft is the early warning; a refusal for the tag still in the form
 * is the API's answer and wins. The two can disagree: the API measures
 * against the project's latest release and re-reads the commits itself,
 * while the form has only its own base tag and a draft that may not have
 * run. Without this, a promote the API refuses could leave no checkbox on
 * screen to satisfy it. The draft's own findings stay listed beside the
 * server's.
 */
export function resolveBreakingGate({
  draftChanges,
  lastTag,
  refusal,
  tag,
}: {
  draftChanges: BreakingChange[] | undefined
  lastTag: null | string
  refusal: BreakingRefusal | null
  tag: string
}): BreakingGate {
  if (refusal && refusal.tag === tag) {
    const seen = new Set(refusal.breaking_changes.map((c) => c.commit))
    return {
      changes: [
        ...refusal.breaking_changes,
        ...(draftChanges ?? []).filter((c) => !seen.has(c.commit)),
      ],
      lastTag: refusal.last_tag,
      needsAck: true,
    }
  }
  return {
    changes: draftChanges ?? [],
    lastTag,
    needsAck: breakingNeedsAcknowledgement(draftChanges, lastTag, tag),
  }
}

const SEMVER_RE = /^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/
// Mirrors CALVER_TAG_PATTERN in imbi.common.versioning; keep in step.
const CALVER_RE = /^\d{4}([.-])\d{1,2}\1\d{1,2}(?:[.-]\w+)?$/

/**
 * Mirrors the API's `_skips_breaking_bump`: `tag` is newer than `lastTag`
 * but keeps the major version (the minor, below 1.0.0). `false` when
 * either is not semver or `tag` is not newer — there is no step to judge.
 * A date (`2026.09.17`) has the semver shape too, but its parts carry no
 * compatibility meaning, so calver tags are never judged either.
 */
export function skipsBreakingBump(lastTag: string, tag: string): boolean {
  if (CALVER_RE.test(lastTag) || CALVER_RE.test(tag)) return false
  const last = parse(lastTag)
  const next = parse(tag)
  if (!last || !next) return false
  const newer =
    next[0] !== last[0]
      ? next[0] > last[0]
      : next[1] !== last[1]
        ? next[1] > last[1]
        : next[2] > last[2]
  if (!newer) return false
  if (last[0] === 0) return next[0] === 0 && next[1] === last[1]
  return next[0] === last[0]
}

/** The bump a breaking change calls for after `lastTag`. */
function breakingBump(lastTag: null | string): 'major' | 'minor' {
  return parse(lastTag ?? '')?.[0] === 0 ? 'minor' : 'major'
}

function parse(tag: string): [number, number, number] | null {
  const match = SEMVER_RE.exec(tag)
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null
}
