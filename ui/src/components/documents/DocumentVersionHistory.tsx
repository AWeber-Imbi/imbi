import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { diffLines } from 'diff'
import type { LucideIcon } from 'lucide-react'
import {
  CircleDashed,
  FileText,
  GitCompare,
  Pencil,
  Plus,
  RotateCcw,
} from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { getDocumentVersion, listDocumentVersions } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { RelativeTime } from '@/components/ui/RelativeTime'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Sk, SkText } from '@/components/ui/skeleton'
import { UserIdentity } from '@/components/ui/user-identity'
import { cn } from '@/lib/utils'
import type { Document, DocumentVersionInfo } from '@/types'

// Each change kind gets a glyph and tone so the timeline itself tells
// the story: how a version came to be, at a glance.
const CHANGE_KINDS: Record<
  DocumentVersionInfo['change_kind'],
  { icon: LucideIcon; label: string; tone: string }
> = {
  baseline: { icon: CircleDashed, label: 'Original', tone: 'text-tertiary' },
  create: { icon: Plus, label: 'Created', tone: 'text-success' },
  restore: { icon: RotateCcw, label: 'Restored', tone: 'text-warning' },
  update: { icon: Pencil, label: 'Edited', tone: 'text-secondary' },
}

interface Props {
  displayNames?: Map<string, string>
  document: Document
  onOpenChange: (open: boolean) => void
  onRestore: (version: number) => void
  open: boolean
  orgSlug: string
  restorePending?: boolean
}

/**
 * Version-history dialog for one document: a timeline of versions on
 * the left (glyphs encode how each came to be), the selected snapshot
 * on the right — rendered, or as a line diff against the current
 * content — with a restore action scoped to the selected version.
 */
export function DocumentVersionHistory({
  displayNames,
  document,
  onOpenChange,
  onRestore,
  open,
  orgSlug,
  restorePending = false,
}: Props) {
  const [selected, setSelected] = useState<null | number>(null)
  const [viewMode, setViewMode] = useState<'content' | 'diff'>('content')
  const [confirmRestore, setConfirmRestore] = useState(false)

  const versionsQuery = useQuery({
    enabled: open,
    queryFn: ({ signal }) => listDocumentVersions(orgSlug, document.id, signal),
    queryKey: ['documentVersions', orgSlug, document.id],
  })
  const versions = versionsQuery.data ?? []
  const selectedVersion = selected ?? versions[0]?.version ?? null
  const selectedInfo =
    versions.find((v) => v.version === selectedVersion) ?? null

  const snapshotQuery = useQuery({
    enabled: open && selectedVersion !== null,
    queryFn: ({ signal }) =>
      getDocumentVersion(orgSlug, document.id, selectedVersion ?? 0, signal),
    queryKey: ['documentVersion', orgSlug, document.id, selectedVersion],
  })
  const snapshot = snapshotQuery.data

  const diffParts = useMemo(
    () => (snapshot ? diffLines(snapshot.content, document.content) : []),
    [snapshot, document.content],
  )
  const diffStats = useMemo(() => {
    let added = 0
    let removed = 0
    for (const part of diffParts) {
      const lines = part.value.replace(/\n$/, '').split('\n').length
      if (part.added) added += lines
      else if (part.removed) removed += lines
    }
    return { added, removed }
  }, [diffParts])

  const currentVersion = document.version ?? 1
  const isCurrent =
    selectedVersion !== null && selectedVersion === currentVersion

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="flex h-[min(85vh,680px)] flex-col gap-0 overflow-hidden p-0 sm:max-w-4xl">
        <DialogHeader className="border-tertiary border-b px-5 pt-5 pb-4">
          <DialogTitle>Version history</DialogTitle>
          <DialogDescription>
            Every saved version of “{document.title}”.
          </DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 grid-cols-1 sm:grid-cols-[248px_minmax(0,1fr)]">
          {/* Timeline rail */}
          <div className="border-tertiary overflow-y-auto border-b p-3 sm:border-r sm:border-b-0">
            {versionsQuery.isLoading && <TimelineSkeleton />}
            {!versionsQuery.isLoading && versions.length === 0 && (
              <div className="text-tertiary p-2 text-sm">
                No versions yet — the next edit records one.
              </div>
            )}
            {versions.length > 0 && (
              <div className="relative">
                {/* The spine: one continuous line through every node. */}
                <div
                  aria-hidden
                  className="bg-tertiary absolute top-4 bottom-4 left-[22px] w-px"
                />
                <div className="relative flex flex-col gap-0.5">
                  {versions.map((v) => (
                    <TimelineEntry
                      current={v.version === currentVersion}
                      displayNames={displayNames}
                      key={v.version}
                      onSelect={() => setSelected(v.version)}
                      selected={v.version === selectedVersion}
                      version={v}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Snapshot pane */}
          <div className="flex min-h-0 flex-col">
            <div className="border-tertiary bg-secondary/50 flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-4 py-2.5">
              {selectedInfo && (
                <div className="text-tertiary flex min-w-0 items-center gap-2 text-[12.5px]">
                  <span className="text-primary font-mono font-medium">
                    v{selectedInfo.version}
                  </span>
                  <span>{CHANGE_KINDS[selectedInfo.change_kind].label}</span>
                  <span aria-hidden>·</span>
                  <UserIdentity
                    displayNames={displayNames}
                    email={selectedInfo.updated_by}
                    linkToProfile={false}
                    size="small"
                  />
                  <RelativeTime value={selectedInfo.updated_at} />
                </div>
              )}
              <div className="ml-auto flex items-center gap-2">
                {viewMode === 'diff' && snapshot && !isCurrent && (
                  <span className="font-mono text-[12.5px] tabular-nums">
                    <span className="text-success">+{diffStats.added}</span>{' '}
                    <span className="text-danger">−{diffStats.removed}</span>
                  </span>
                )}
                <SegmentedControl
                  ariaLabel="Version view"
                  onValueChange={(v) => setViewMode(v as 'content' | 'diff')}
                  value={viewMode}
                >
                  <SegmentedControlItem value="content">
                    <FileText className="size-3" />
                    Content
                  </SegmentedControlItem>
                  <SegmentedControlItem value="diff">
                    <GitCompare className="size-3" />
                    Changes
                  </SegmentedControlItem>
                </SegmentedControl>
                {!isCurrent && selectedVersion !== null && (
                  <Button
                    className="gap-1.5"
                    disabled={!snapshot || restorePending}
                    onClick={() => setConfirmRestore(true)}
                    size="sm"
                    variant="outline"
                  >
                    <RotateCcw className="size-3" />
                    {restorePending
                      ? 'Restoring…'
                      : `Restore v${selectedVersion}`}
                  </Button>
                )}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
              {snapshotQuery.isLoading && (
                <div className="flex flex-col gap-3">
                  <Sk h={22} w="33%" />
                  <SkText widths={['100%', '83%', '66%']} />
                </div>
              )}
              {snapshot && viewMode === 'content' && (
                <>
                  <h2 className="text-primary mt-0 mb-3 text-lg font-medium">
                    {snapshot.title}
                  </h2>
                  <div className="document-markdown">
                    <Markdown remarkPlugins={[remarkGfm]}>
                      {snapshot.content}
                    </Markdown>
                  </div>
                </>
              )}
              {snapshot &&
                viewMode === 'diff' &&
                (isCurrent ? (
                  <div className="text-tertiary text-sm italic">
                    This is the current version — nothing to compare.
                  </div>
                ) : (
                  <DiffView parts={diffParts} />
                ))}
            </div>
          </div>
        </div>
      </DialogContent>

      <ConfirmDialog
        confirmLabel={restorePending ? 'Restoring…' : 'Restore'}
        description={`“${document.title}” will be reverted to version ${selectedVersion}. The current content is kept in the history as its own version — nothing is overwritten.`}
        onCancel={() => setConfirmRestore(false)}
        onConfirm={() => {
          setConfirmRestore(false)
          if (selectedVersion !== null) onRestore(selectedVersion)
        }}
        open={confirmRestore}
        title={`Restore version ${selectedVersion}?`}
      />
    </Dialog>
  )
}

/**
 * Line diff from the selected snapshot to the current content:
 * additions are lines the current document gained since that version,
 * removals are lines only that version had.
 */
function DiffView({ parts }: { parts: ReturnType<typeof diffLines> }) {
  if (parts.length === 1 && !parts[0].added && !parts[0].removed) {
    return (
      <div className="text-tertiary text-sm italic">
        This version's content is identical to the current document.
      </div>
    )
  }
  return (
    <div className="font-mono text-[12.5px] leading-[1.6] whitespace-pre-wrap">
      {parts.flatMap((part, i) => {
        const lines = part.value.replace(/\n$/, '').split('\n')
        return lines.map((line, j) => (
          <div
            className={cn(
              'rounded-sm px-2',
              part.added && 'text-success bg-success/10',
              part.removed && 'text-danger bg-danger/10',
            )}
            key={`${i}-${j}`}
          >
            <span className="inline-block w-4 select-none">
              {part.added ? '+' : part.removed ? '−' : ' '}
            </span>
            {line}
          </div>
        ))
      })}
    </div>
  )
}

function TimelineEntry({
  current,
  displayNames,
  onSelect,
  selected,
  version,
}: {
  current: boolean
  displayNames?: Map<string, string>
  onSelect: () => void
  selected: boolean
  version: DocumentVersionInfo
}) {
  const kind = CHANGE_KINDS[version.change_kind]
  const Icon = kind.icon
  return (
    <button
      className={cn(
        'focus-visible:ring-ring grid cursor-pointer grid-cols-[28px_minmax(0,1fr)] items-start gap-x-2.5 rounded-md p-2 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none',
        selected ? 'bg-secondary' : 'hover:bg-secondary/60',
      )}
      onClick={onSelect}
      type="button"
    >
      {/* Node on the spine */}
      <span
        className={cn(
          'bg-primary mt-0.5 flex size-[26px] items-center justify-center rounded-full border',
          selected ? 'border-action' : 'border-secondary',
          kind.tone,
        )}
      >
        <Icon className="size-3" />
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-[12.5px]">
          <span className="text-primary font-mono font-medium">
            v{version.version}
          </span>
          <span className="text-tertiary">{kind.label}</span>
          {current && (
            <span className="border-action/40 text-action ml-auto rounded-full border px-1.5 text-[11px] leading-[1.6]">
              Current
            </span>
          )}
        </span>
        <span className="text-tertiary flex items-center gap-1.5 text-[11.5px]">
          <UserIdentity
            displayNames={displayNames}
            email={version.updated_by}
            linkToProfile={false}
            size="small"
          />
          <span aria-hidden>·</span>
          <RelativeTime value={version.updated_at} />
        </span>
      </span>
    </button>
  )
}

function TimelineSkeleton() {
  return (
    <div className="flex flex-col gap-3 p-2">
      {[0, 1, 2].map((i) => (
        <div className="grid grid-cols-[28px_1fr] items-center gap-2.5" key={i}>
          <Sk circle h={26} w={26} />
          <div className="flex flex-col gap-1.5">
            <Sk line w={96} />
            <Sk line w={128} />
          </div>
        </div>
      ))}
    </div>
  )
}
