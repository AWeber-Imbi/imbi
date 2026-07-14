import { useState } from 'react'

import { Link } from 'react-router-dom'

import { CheckCircle2, Clipboard, ClockIcon, XCircle } from 'lucide-react'

import type { EventHandlerOutcome, EventRecord } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

interface DispositionMeta {
  label: string
  tone: 'failure' | 'pending' | 'success'
}

interface WebhookHistoryRowProps {
  defaultOpen?: boolean
  event: EventRecord
  projectLabel?: string
}

export function WebhookHistoryRow({
  defaultOpen = false,
  event,
  projectLabel,
}: WebhookHistoryRowProps) {
  const [open, setOpen] = useState(defaultOpen)
  const handlers = getHandlers(event.metadata)
  const disposition = deriveDisposition(handlers)
  const webhookId = getWebhookId(event.metadata)
  const headers = getRedactedHeaders(event.metadata)
  // The per-source label (e.g. 'pull_request') lives in
  // `metadata.event_type`. Old rows recorded before the
  // category/subtype split carried it as the top-level `type`, so
  // fall back to that for display only.
  const eventTypeLabel =
    getMetadataString(event.metadata, 'event_type') ||
    event.type ||
    '(unspecified)'

  const dispositionVariant =
    disposition.tone === 'success'
      ? 'default'
      : disposition.tone === 'failure'
        ? 'destructive'
        : 'secondary'

  const onCopyLink = () => {
    const url = `${window.location.origin}/admin/webhook-history/${encodeURIComponent(event.id)}`
    void navigator.clipboard.writeText(url)
  }

  return (
    <div
      className="rounded-md border border-slate-200 bg-white"
      data-testid="webhook-history-row"
    >
      <button
        aria-expanded={open}
        className="flex w-full items-center gap-3 px-4 py-3 text-left"
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <ClockIcon className="text-tertiary size-4" />
        <span className="text-secondary text-sm tabular-nums">
          {new Date(event.recorded_at).toLocaleString()}
        </span>
        <Badge variant="secondary">{event.integration}</Badge>
        <span className="text-primary text-sm font-medium">
          {eventTypeLabel}
        </span>
        <span className="text-secondary text-sm">
          {projectLabel ?? event.project_id}
        </span>
        {event.attributed_to ? (
          <span className="text-secondary text-xs">
            attributed to {event.attributed_to}
          </span>
        ) : null}
        <span className="ml-auto inline-flex items-center gap-1">
          <Badge variant={dispositionVariant}>{disposition.label}</Badge>
        </span>
      </button>
      {open ? (
        <div className="space-y-3 border-t border-slate-200 bg-slate-50 px-4 py-3 text-sm">
          <div className="flex items-center justify-between">
            <div className="text-secondary text-xs">
              project:{' '}
              <Link
                className="text-amber-text hover:underline"
                to={`/projects/${event.project_id}`}
              >
                <code>{projectLabel ?? event.project_id}</code>
              </Link>{' '}
              · event id: <code>{event.id}</code>
              {webhookId ? (
                <>
                  {' '}
                  · webhook id: <code>{webhookId}</code>
                </>
              ) : null}
            </div>
            <Button
              aria-label="Copy event link"
              onClick={onCopyLink}
              size="sm"
              type="button"
              variant="outline"
            >
              <Clipboard className="mr-1 size-3" />
              Copy link
            </Button>
          </div>
          <div>
            <div className="text-secondary mb-1 text-xs font-medium uppercase">
              Handlers
            </div>
            {handlers.length === 0 ? (
              <div className="text-tertiary text-xs">
                No handlers fired (filter did not match or no rules).
              </div>
            ) : (
              <ul className="space-y-1">
                {handlers.map((h, i) => (
                  <li
                    className="flex items-center gap-2"
                    key={`${h.handler}-${i}`}
                  >
                    {h.status === 'succeeded' ? (
                      <CheckCircle2 className="size-3 text-emerald-600" />
                    ) : (
                      <XCircle className="size-3 text-rose-600" />
                    )}
                    <code className="text-xs">{h.handler}</code>
                    <span className="text-secondary text-xs">{h.status}</span>
                    {typeof h.duration_ms === 'number' ? (
                      <span className="text-tertiary text-xs">
                        {h.duration_ms}ms
                      </span>
                    ) : null}
                    {h.error ? (
                      <span className="text-xs text-rose-700">{h.error}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            )}
          </div>
          {Object.keys(headers).length > 0 ? (
            <details>
              <summary className="text-secondary cursor-pointer text-xs font-medium uppercase">
                Headers
              </summary>
              <pre className="mt-1 overflow-x-auto rounded bg-slate-100 p-2 text-xs">
                {JSON.stringify(headers, null, 2)}
              </pre>
            </details>
          ) : null}
          <details>
            <summary className="text-secondary cursor-pointer text-xs font-medium uppercase">
              Payload
            </summary>
            <pre className="mt-1 overflow-x-auto rounded bg-slate-100 p-2 text-xs">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </details>
        </div>
      ) : null}
    </div>
  )
}

function deriveDisposition(handlers: EventHandlerOutcome[]): DispositionMeta {
  if (handlers.length === 0) {
    return { label: 'Recorded · no handlers', tone: 'pending' }
  }
  const succeeded = handlers.filter((h) => h.status === 'succeeded').length
  const failed = handlers.filter((h) => h.status === 'failed').length
  if (failed === 0) {
    return { label: `${succeeded} handlers · ok`, tone: 'success' }
  }
  return {
    label: `${succeeded} of ${handlers.length} handlers ok`,
    tone: 'failure',
  }
}

function getHandlers(metadata: Record<string, unknown>): EventHandlerOutcome[] {
  const raw = metadata.handlers
  return Array.isArray(raw) ? (raw as EventHandlerOutcome[]) : []
}

function getMetadataString(
  metadata: Record<string, unknown>,
  key: string,
): string {
  const raw = metadata[key]
  return typeof raw === 'string' ? raw : ''
}

function getRedactedHeaders(
  metadata: Record<string, unknown>,
): Record<string, string> {
  const raw = metadata.headers
  if (raw && typeof raw === 'object') {
    return raw as Record<string, string>
  }
  return {}
}

function getWebhookId(metadata: Record<string, unknown>): string {
  return getMetadataString(metadata, 'webhook_id')
}
