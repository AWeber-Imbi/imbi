import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { diffLines } from 'diff'
import { FileText, GitCompare, RotateCcw } from 'lucide-react'
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
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { UserIdentity } from '@/components/ui/user-identity'
import { cn } from '@/lib/utils'
import type { Document, DocumentVersionInfo } from '@/types'

import { formatFull } from './documentsHelpers'

const CHANGE_KIND_LABELS: Record<DocumentVersionInfo['change_kind'], string> = {
  baseline: 'Original',
  create: 'Created',
  restore: 'Restored',
  update: 'Edited',
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
 * Version-history dialog for one document: version list on the left,
 * the selected snapshot (rendered, or a line diff against the current
 * content) on the right, with a restore action.
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

  const snapshotQuery = useQuery({
    enabled: open && selectedVersion !== null,
    queryFn: ({ signal }) =>
      getDocumentVersion(orgSlug, document.id, selectedVersion ?? 0, signal),
    queryKey: ['documentVersion', orgSlug, document.id, selectedVersion],
  })
  const snapshot = snapshotQuery.data

  const isCurrent =
    selectedVersion !== null && selectedVersion === (document.version ?? 1)

  return (
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="flex max-h-[85vh] flex-col sm:max-w-4xl">
        <DialogHeader>
          <DialogTitle>Version history</DialogTitle>
          <DialogDescription>
            Every saved change to “{document.title}”. Restoring an older version
            saves it as a new version — nothing is overwritten.
          </DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 sm:grid-cols-[220px_minmax(0,1fr)]">
          {/* Version list */}
          <div className="border-tertiary flex max-h-[60vh] flex-col gap-1 overflow-y-auto sm:border-r sm:pr-3">
            {versionsQuery.isLoading && (
              <div className="text-tertiary p-2 text-sm">Loading…</div>
            )}
            {!versionsQuery.isLoading && versions.length === 0 && (
              <div className="text-tertiary p-2 text-sm">
                No history recorded yet. Versions are captured from the next
                edit onward.
              </div>
            )}
            {versions.map((v) => (
              <button
                className={cn(
                  'cursor-pointer rounded-md border p-2 text-left transition-colors',
                  v.version === selectedVersion
                    ? 'border-action bg-secondary'
                    : 'border-transparent hover:bg-secondary',
                )}
                key={v.version}
                onClick={() => setSelected(v.version)}
                type="button"
              >
                <div className="text-primary flex items-center gap-1.5 text-[12.5px] font-medium">
                  v{v.version}
                  <span className="text-tertiary font-normal">
                    {CHANGE_KIND_LABELS[v.change_kind]}
                  </span>
                  {v.version === (document.version ?? 1) && (
                    <span className="text-action font-normal">· current</span>
                  )}
                </div>
                <div className="text-tertiary mt-0.5 text-[11.5px]">
                  {formatFull(v.updated_at)}
                </div>
                <div className="mt-1">
                  <UserIdentity
                    displayNames={displayNames}
                    email={v.updated_by}
                    linkToProfile={false}
                    size="small"
                  />
                </div>
              </button>
            ))}
          </div>

          {/* Snapshot pane */}
          <div className="flex min-h-0 flex-col">
            <div className="mb-2 flex items-center gap-2">
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
                  Changes vs current
                </SegmentedControlItem>
              </SegmentedControl>
              <Button
                className="ml-auto gap-1.5"
                disabled={
                  !snapshot || isCurrent || restorePending || !selectedVersion
                }
                onClick={() => setConfirmRestore(true)}
                size="sm"
                variant="outline"
              >
                <RotateCcw className="size-3" />
                {restorePending ? 'Restoring…' : 'Restore this version'}
              </Button>
            </div>

            <div className="border-tertiary min-h-0 flex-1 overflow-y-auto rounded-md border p-4">
              {snapshotQuery.isLoading && (
                <div className="text-tertiary text-sm">Loading version…</div>
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
              {snapshot && viewMode === 'diff' && (
                <DiffView current={document.content} old={snapshot.content} />
              )}
            </div>
          </div>
        </div>
      </DialogContent>

      <ConfirmDialog
        confirmLabel={restorePending ? 'Restoring…' : 'Restore'}
        description={`The document will be reverted to version ${selectedVersion}. The current content stays in the history as its own version.`}
        onCancel={() => setConfirmRestore(false)}
        onConfirm={() => {
          setConfirmRestore(false)
          if (selectedVersion !== null) onRestore(selectedVersion)
        }}
        open={confirmRestore}
        title="Restore this version?"
      />
    </Dialog>
  )
}

/**
 * Line diff between the selected snapshot and the current content.
 * Additions are lines the current document has that the snapshot
 * doesn't; removals are lines only the snapshot has.
 */
function DiffView({ current, old }: { current: string; old: string }) {
  const parts = useMemo(() => diffLines(old, current), [old, current])
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
              'px-2',
              part.added &&
                'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400',
              part.removed && 'bg-red-500/10 text-red-700 dark:text-red-400',
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
