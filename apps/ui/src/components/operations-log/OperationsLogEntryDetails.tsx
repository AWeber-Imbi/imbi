import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { getOperationsLogEntry } from '@/api/endpoints'
import type { OperationsLogRecord } from '@/types'

interface Props {
  entry: OperationsLogRecord
}

function parseUtcIso(iso: string): Date {
  const hasOffset = /(Z|[+-]\d\d:?\d\d)$/.test(iso)
  return new Date(hasOffset ? iso : iso + 'Z')
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
  label,
  children,
  title,
}: {
  label: string
  children: React.ReactNode
  title?: string
}) {
  return (
    <span className="inline-flex items-baseline gap-1.5" title={title}>
      <span className="text-overline uppercase text-tertiary">{label}</span>
      <span className="text-primary">{children}</span>
    </span>
  )
}

export function OperationsLogEntryDetails({ entry }: Props) {
  const { data } = useQuery({
    queryKey: ['operationsLog', 'entry', entry.id],
    queryFn: ({ signal }) => getOperationsLogEntry(entry.id, signal),
    initialData: entry,
    staleTime: 30_000,
  })

  const record = data ?? entry
  const performer = record.performed_by ?? record.recorded_by

  // Notes from the v1 migration often duplicate the description; suppress
  // identical notes so the panel shows real long-form content only.
  const hasNotes =
    !!record.notes && record.notes.trim() !== record.description.trim()

  const hasExtras =
    hasNotes ||
    !!record.link ||
    !!record.ticket_slug ||
    !!record.completed_at ||
    record.recorded_by !== performer

  return (
    <div className="space-y-4 py-4 pl-[60px] pr-4">
      {hasNotes && (
        <div>
          <h3 className="mb-1.5 text-overline uppercase text-tertiary">
            Notes
          </h3>
          <div className="prose prose-sm dark:prose-invert max-w-none rounded-md border border-tertiary bg-primary p-3 text-primary [&>*:first-child]:mt-0 [&>*:last-child]:mb-0">
            <Markdown remarkPlugins={[remarkGfm]}>{record.notes}</Markdown>
          </div>
        </div>
      )}

      {record.link && (
        <div>
          <h3 className="mb-1.5 text-overline uppercase text-tertiary">Link</h3>
          <a
            href={record.link}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 break-all text-sm text-amber-text hover:underline"
          >
            <ExternalLink className="h-3.5 w-3.5 flex-shrink-0" />
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
        <p className="text-sm text-tertiary">
          No additional notes, link, or ticket for this entry.
        </p>
      )}
    </div>
  )
}
