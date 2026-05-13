import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Copy, ExternalLink } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { getOperationsLogEntry } from '@/api/endpoints'
import {
  NewOpsLogDialog,
  type NewOpsLogInitialValues,
} from '@/components/NewOpsLogDialog'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import type { OperationsLogRecord } from '@/types'

import { parseDescription } from './parseDescription'
import {
  GenericPluginPayload,
  type PluginOpsLogContext,
} from './plugin-renderers'

interface Props {
  entry: OperationsLogRecord
}

// Predominantly a render function whose branches gate which optional
// metadata sections appear (notes, link, ticket, plugin payload).
// Each branch is straight-line markup, not nested logic. This PR
// reduces the function's cyclomatic complexity (24 → 19) by removing
// the legacy plugin-renderer branch, but fallow's audit attributes the
// remaining threshold breach to this change. Keep the suppression
// scoped to the function header until the component is split per
// optional section.
// fallow-ignore-next-line complexity
export function OperationsLogEntryDetails({ entry }: Props) {
  const { data } = useQuery({
    initialData: entry,
    queryFn: ({ signal }) => getOperationsLogEntry(entry.id, signal),
    queryKey: ['operationsLog', 'entry', entry.id],
    staleTime: 30_000,
  })

  const record = data ?? entry
  const performer = record.performed_by ?? record.recorded_by
  const [duplicateOpen, setDuplicateOpen] = useState(false)

  const duplicateInitialValues: NewOpsLogInitialValues = {
    description: record.description,
    entry_type: record.entry_type,
    environment_slug: record.environment_slug,
    link: record.link,
    notes: record.notes,
    project_id: record.project_id,
    ticket_slug: record.ticket_slug,
    version: record.version,
  }
  const parsed = parseDescription(record)
  const pluginCtx: null | PluginOpsLogContext =
    parsed.kind === 'plugin'
      ? { action: parsed.action, entry: record, payload: parsed.payload }
      : null

  // Notes from the v1 migration often duplicate the free-text description;
  // suppress identical notes so the panel shows real long-form content only.
  // Plugin-emitted entries don't share that lineage, so the comparison is
  // skipped when `description` carries a structured payload.
  const sanitizedNotes = record.notes ? cleanNotes(record.notes) : ''
  const hasNotes =
    !!sanitizedNotes &&
    (parsed.kind === 'plugin' ||
      sanitizedNotes.trim() !== record.description.trim())

  const hasExtras =
    hasNotes ||
    !!pluginCtx ||
    !!record.link ||
    !!record.ticket_slug ||
    !!record.completed_at ||
    record.recorded_by !== performer

  return (
    <div className="space-y-4 py-4 pr-4 pl-15">
      {pluginCtx && (
        <div>
          <h3 className="text-overline text-tertiary mb-1.5 uppercase">
            {record.plugin_slug}
          </h3>
          <div className="border-tertiary bg-primary rounded-md border p-3">
            <GenericPluginPayload {...pluginCtx} />
          </div>
        </div>
      )}
      {hasNotes && (
        <div>
          <h3 className="text-overline text-tertiary mb-1.5 uppercase">
            Notes
          </h3>
          <div className="document-markdown border-tertiary bg-primary text-primary max-w-none rounded-md border p-3 [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <Markdown remarkPlugins={[remarkGfm]}>{sanitizedNotes}</Markdown>
          </div>
        </div>
      )}

      {record.link && (
        <div>
          <h3 className="text-overline text-tertiary mb-1.5 uppercase">Link</h3>
          <a
            className="text-amber-text inline-flex items-center gap-1.5 text-sm break-all hover:underline"
            href={record.link}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalLink className="size-3.5 shrink-0" />
            {record.link}
          </a>
        </div>
      )}

      <div className="flex flex-wrap items-baseline gap-x-5 gap-y-2 text-xs">
        {record.ticket_slug && (
          <MetaChip label="Ticket">
            <code className="font-mono">{record.ticket_slug}</code>
          </MetaChip>
        )}

        {record.completed_at && (
          <MetaChip label="Completed">
            {formatAbsolute(record.completed_at)}
          </MetaChip>
        )}

        {record.recorded_by !== performer && (
          <MetaChip label="Recorded by">
            <span className="text-secondary">{record.recorded_by}</span>
          </MetaChip>
        )}

        <MetaChip label="Occurred">
          <TooltipProvider delayDuration={300}>
            <Tooltip>
              <TooltipTrigger asChild>
                <span>{formatAbsolute(record.occurred_at)}</span>
              </TooltipTrigger>
              <TooltipContent>{record.occurred_at}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </MetaChip>
      </div>

      {!hasExtras && (
        <p className="text-tertiary text-sm">
          No additional notes, link, or ticket for this entry.
        </p>
      )}

      <div className="flex justify-end pt-2">
        <Button
          onClick={() => setDuplicateOpen(true)}
          size="sm"
          variant="outline"
        >
          <Copy className="mr-1.5 size-3.5" />
          Duplicate
        </Button>
      </div>

      <NewOpsLogDialog
        initialValues={duplicateInitialValues}
        isOpen={duplicateOpen}
        onClose={() => setDuplicateOpen(false)}
      />
    </div>
  )
}

function cleanNotes(notes: string): string {
  return notes
    .replace(/\\n/g, '\n')
    .replace(/<!--[\s\S]*?-->/g, '')
    .trim()
}

function formatAbsolute(iso: string): string {
  try {
    return parseUtcIso(iso).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    })
  } catch {
    return iso
  }
}

function MetaChip({
  children,
  label,
  title,
}: {
  children: React.ReactNode
  label: string
  title?: string
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5" title={title}>
      <span className="text-overline text-tertiary uppercase">{label}</span>
      <span className="text-primary">{children}</span>
    </span>
  )
}

function parseUtcIso(iso: string): Date {
  const hasOffset = /(Z|[+-]\d\d:?\d\d)$/.test(iso)
  return new Date(hasOffset ? iso : iso + 'Z')
}
