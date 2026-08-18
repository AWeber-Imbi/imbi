import { useState } from 'react'

import {
  Ban,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  ShieldAlert,
} from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { UserIdentity } from '@/components/ui/user-identity'
import { cn } from '@/lib/utils'
import type { ReleaseBlocker, ReleaseHistoryEntry } from '@/types'

import { AddBlockerDialog, BLOCKER_TYPES } from './AddBlockerDialog'
import type { ArtifactInfo } from './artifact'
import { CiStatusDot } from './CiStatusDot'
import { useReleaseBlockMutation } from './useReleaseBlockMutation'

interface BlockedNoteProps {
  blockers: ReleaseBlocker[]
  isPending: boolean
  onResolve: (blockerId: string) => void
  onUnblock: () => void
  rel: ReleaseHistoryEntry
}

/** Human label for a blocker type, falling back to the raw value. */
const typeLabel = (value: string): string =>
  BLOCKER_TYPES.find((option) => option.value === value)?.label ?? value

/**
 * The blockers to render for a release. A release blocked before the
 * Blocker model shipped has the mirrored `blocked_*` fields and no list,
 * so one is synthesized from them rather than showing "Blocked" with
 * nothing under it.
 */
const openBlockers = (rel: ReleaseHistoryEntry): ReleaseBlocker[] => {
  if (rel.blockers?.length) return rel.blockers
  if (!rel.blocked) return []
  return [
    {
      created_at: rel.blocked_at,
      created_by: rel.blocked_by,
      description: rel.blocked_reason ?? '',
      id: '',
      status: 'open',
      type: 'manual',
    },
  ]
}

interface ReleaseHistoryProps {
  artifact: ArtifactInfo
  currentTag: null | string
  orgSlug: string
  projectId: string
  releases: ReleaseHistoryEntry[]
}

interface ReleaseRowProps {
  artifact: ArtifactInfo
  isCurrent: boolean
  isOpen: boolean
  isPending: boolean
  onBlock: () => void
  onResolve: (blockerId: string) => void
  onToggle: () => void
  onUnblock: () => void
  rel: ReleaseHistoryEntry
}

export function ReleaseHistory({
  artifact,
  currentTag,
  orgSlug,
  projectId,
  releases,
}: ReleaseHistoryProps) {
  const [open, setOpen] = useState<null | string>(null)
  const [blocking, setBlocking] = useState<null | string>(null)
  const { block, isPending, resolve, unblock } = useReleaseBlockMutation({
    orgSlug,
    projectId,
  })
  if (releases.length === 0) return null
  return (
    <div className="border-tertiary mt-3 border-t pt-3">
      <p className="text-tertiary mb-2 text-xs tracking-wider uppercase">
        Release history
      </p>
      <div>
        {releases.map((rel) => (
          <ReleaseRow
            artifact={artifact}
            isCurrent={rel.tag === currentTag}
            isOpen={open === rel.tag}
            isPending={isPending}
            key={rel.tag}
            onBlock={() => setBlocking(rel.tag)}
            onResolve={(blockerId) => resolve({ blockerId, tag: rel.tag })}
            onToggle={() => setOpen((o) => (o === rel.tag ? null : rel.tag))}
            onUnblock={() => unblock(rel.tag)}
            rel={rel}
          />
        ))}
      </div>
      <AddBlockerDialog
        isPending={isPending}
        onBlock={(type, description) => {
          if (blocking) block({ description, tag: blocking, type })
          setBlocking(null)
        }}
        onOpenChange={(next) => {
          if (!next) setBlocking(null)
        }}
        open={blocking !== null}
        tag={blocking ?? ''}
      />
    </div>
  )
}

/** Every open blocker on the release, and how to clear them. */
function BlockedNote({
  blockers,
  isPending,
  onResolve,
  onUnblock,
  rel,
}: BlockedNoteProps) {
  return (
    <div className="border-danger bg-danger text-danger mt-1 mb-3 rounded-md border px-3 py-2.5">
      <div className="flex items-start gap-2">
        <Ban className="mt-0.5 size-3.5 shrink-0" />
        <p className="min-w-0 flex-1 text-xs leading-relaxed">
          Blocked from deploying and promoting until
          {blockers.length === 1 ? ' this is resolved' : ' these are resolved'}
        </p>
        <Button
          className="h-auto shrink-0 px-2 py-1 text-xs"
          disabled={isPending}
          onClick={onUnblock}
          type="button"
          variant="outline"
        >
          {blockers.length === 1 ? 'Unblock' : 'Resolve all'}
        </Button>
      </div>
      <ul className="mt-2 flex flex-col gap-1.5">
        {blockers.map((blocker, index) => (
          <li
            className="flex items-start gap-2 text-xs leading-relaxed"
            key={blocker.id || `${rel.tag}-${index}`}
          >
            <Badge className="mt-px shrink-0" variant="danger">
              {typeLabel(blocker.type)}
            </Badge>
            <span className="min-w-0 flex-1">
              {blocker.description}
              {blocker.created_by ? (
                <span className="opacity-80">
                  {' · '}
                  {blocker.created_by}
                  {blocker.created_at ? (
                    <>
                      {' · '}
                      <RelativeTime
                        tooltip={false}
                        value={blocker.created_at}
                      />
                    </>
                  ) : null}
                </span>
              ) : null}
            </span>
            {blocker.id ? (
              <Button
                className="h-auto shrink-0 px-2 py-0.5 text-xs"
                disabled={isPending}
                onClick={() => onResolve(blocker.id)}
                type="button"
                variant="ghost"
              >
                Resolve
              </Button>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

/**
 * The record of an operator shipping over a failing CI run.
 *
 * Distinct from the row's `CiStatusDot`, which reports the commit's CI
 * state *now* — a re-run can turn it green long after the fact, and the
 * decision that was made still stands.
 */
function CiOverrideNote({ rel }: { rel: ReleaseHistoryEntry }) {
  return (
    <div className="border-warning bg-warning text-warning mt-1 mb-3 flex items-start gap-2 rounded-md border px-3 py-2.5">
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0" />
      <div className="min-w-0 flex-1 text-xs leading-relaxed">
        <p>Released over a failing CI run</p>
        <p className="mt-1 opacity-80">
          acknowledged by {rel.ci_override_by}
          {rel.ci_override_at ? (
            <>
              {' · '}
              <RelativeTime tooltip={false} value={rel.ci_override_at} />
            </>
          ) : null}
        </p>
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function ReleaseRow({
  artifact,
  isCurrent,
  isOpen,
  isPending,
  onBlock,
  onResolve,
  onToggle,
  onUnblock,
  rel,
}: ReleaseRowProps) {
  const blockers = openBlockers(rel)
  const blocked = blockers.length > 0
  return (
    <div
      className={cn(
        '-mx-2 rounded-md transition-colors',
        isOpen && 'bg-secondary',
      )}
    >
      <button
        className="hover:bg-secondary grid w-full grid-cols-[auto_auto_auto_1fr_auto] items-center gap-3 rounded-md px-2 py-1.5 text-left"
        onClick={onToggle}
        type="button"
      >
        {isOpen ? (
          <ChevronDown className="text-tertiary size-3.5" />
        ) : (
          <ChevronRight className="text-tertiary size-3.5" />
        )}
        <span className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold">{rel.tag}</span>
          <CiStatusDot size={13} status={rel.ci_status} />
        </span>
        <span className="text-tertiary font-mono text-xs">{rel.short_sha}</span>
        <RelativeTime
          className="text-tertiary text-xs"
          tooltip={false}
          value={rel.published_at}
        />
        <span className="flex items-center gap-1.5">
          {blocked ? (
            <Badge className="inline-flex items-center gap-1" variant="danger">
              <Ban className="size-3" />
              Blocked
              {blockers.length > 1 ? ` (${blockers.length})` : null}
            </Badge>
          ) : null}
          {rel.ci_override_by ? (
            <Badge className="inline-flex items-center gap-1" variant="warning">
              <ShieldAlert className="size-3" />
              CI overridden
            </Badge>
          ) : null}
          {isCurrent ? <Badge variant="accent">Latest</Badge> : null}
        </span>
      </button>
      {isOpen ? (
        <div className="px-2 pb-3 pl-[2.1rem]">
          {blocked ? (
            <BlockedNote
              blockers={blockers}
              isPending={isPending}
              onResolve={onResolve}
              onUnblock={onUnblock}
              rel={rel}
            />
          ) : null}
          {rel.ci_override_by ? <CiOverrideNote rel={rel} /> : null}
          {rel.notes_markdown ? (
            <div className="document-markdown max-w-none text-sm [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
              <Markdown
                components={{
                  a: (props) => (
                    <a {...props} rel="noopener noreferrer" target="_blank" />
                  ),
                }}
                remarkPlugins={[remarkGfm]}
              >
                {rel.notes_markdown}
              </Markdown>
            </div>
          ) : (
            <p className="text-tertiary text-xs">No release notes.</p>
          )}
          <div className="mt-2 flex flex-wrap items-center gap-4">
            {rel.author ? (
              <span className="text-tertiary inline-flex items-center gap-1.5 text-xs">
                released by
                <UserIdentity
                  actor={rel.author}
                  email={rel.author_email}
                  size="small"
                />
              </span>
            ) : null}
            {(rel.release_url ?? rel.tag_url) ? (
              <a
                className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
                href={(rel.release_url ?? rel.tag_url) as string}
                rel="noopener noreferrer"
                target="_blank"
              >
                <ExternalLink size={12} />
                {rel.release_url ? 'Release notes' : 'View tag'}
              </a>
            ) : null}
            {artifact.indexUrl ? (
              <a
                className="text-tertiary hover:text-primary inline-flex items-center gap-1 text-xs"
                href={artifact.indexUrl}
                rel="noopener noreferrer"
                target="_blank"
              >
                <artifact.icon size={12} />
                {artifact.indexLabel ?? 'Package index'}
              </a>
            ) : null}
            <Button
              className="text-tertiary hover:text-danger ml-auto h-auto gap-1 px-0 py-0 text-xs"
              disabled={isPending}
              onClick={onBlock}
              type="button"
              variant="ghost"
            >
              <Ban className="size-3" />
              Add blocker
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
