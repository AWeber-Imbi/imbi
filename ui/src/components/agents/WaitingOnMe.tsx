import type { ReactNode } from 'react'

import { Link } from 'react-router-dom'

import { Badge } from '@/components/ui/badge'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { TicketWaiting } from '@/types'

import { ticketsPath } from './agentsNav'
import { statusLabel, statusVariant } from './taskEvents'
import { errorMessage, useWaiting } from './taskQueries'

type WaitingTicket = NonNullable<TicketWaiting['assigned']>[number]

/**
 * Waiting on me (ADR 0028): the open requests on the caller's tickets,
 * the person tickets assigned to them, and their held tickets whose
 * gating prerequisite failed. Each row opens its ticket.
 */
export function WaitingOnMe() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const { data, error, isLoading } = useWaiting(orgSlug || undefined)
  const open = (shortId: string) => ticketsPath(orgSlug, shortId)
  if (error)
    return (
      <p className="text-danger p-8 text-sm" role="alert">
        {errorMessage(error)}
      </p>
    )
  if (isLoading || !data)
    return <p className="text-tertiary p-8 text-sm">Loading…</p>
  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-4 p-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-lg font-medium">Waiting on me</h1>
        <Link
          className="text-action text-sm hover:underline"
          to={ticketsPath()}
        >
          All tickets
        </Link>
      </div>
      <Section
        empty="No questions wait on you."
        title="Questions on your tickets"
      >
        {(data.requests ?? []).map((r) => (
          <Row
            key={r.id}
            meta={r.kind === 'approval' ? 'Approval' : 'Question'}
            shortId={r.short_id}
            subtitle={r.ticket_title}
            title={r.title}
            to={open(r.short_id)}
          />
        ))}
      </Section>
      <Section empty="No tickets are assigned to you." title="Assigned to you">
        {(data.assigned ?? []).map((t) => (
          <TicketRow key={t.short_id} task={t} to={open(t.short_id)} />
        ))}
      </Section>
      <Section
        empty="None of your held tickets has a failed prerequisite."
        title="Held: a prerequisite failed"
      >
        {(data.held ?? []).map((t) => (
          <TicketRow
            key={t.short_id}
            note={`Failed: ${(t.failed ?? []).join(', ')}`}
            task={t}
            to={open(t.short_id)}
          />
        ))}
      </Section>
    </div>
  )
}

function Row({
  meta,
  shortId,
  subtitle,
  title,
  to,
}: {
  meta: ReactNode
  shortId: string
  subtitle?: string
  title: string
  to: string
}) {
  return (
    <li className="border-tertiary border-b last:border-b-0">
      <Link
        className="hover:bg-secondary flex items-center gap-3 px-5 py-2.5"
        to={to}
      >
        <span className="text-tertiary w-14 shrink-0 font-mono text-xs">
          {shortId}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm">{title}</span>
          {subtitle && (
            <span className="text-tertiary block truncate text-xs">
              {subtitle}
            </span>
          )}
        </span>
        <span className="shrink-0">{meta}</span>
      </Link>
    </li>
  )
}

function Section({
  children,
  empty,
  title,
}: {
  children: ReactNode[]
  empty: string
  title: string
}) {
  return (
    <section
      aria-label={title}
      className="border-tertiary bg-primary rounded-lg border"
    >
      <h2 className="border-tertiary text-secondary flex items-center justify-between border-b px-5 py-3 text-sm font-medium">
        {title}
        <span className="text-tertiary font-mono text-xs tabular-nums">
          {children.length}
        </span>
      </h2>
      {children.length ? (
        <ul>{children}</ul>
      ) : (
        <p className="text-tertiary px-5 py-6 text-center text-sm">{empty}</p>
      )}
    </section>
  )
}

function TicketRow({
  note,
  task,
  to,
}: {
  note?: string
  task: WaitingTicket
  to: string
}) {
  return (
    <Row
      meta={<Badge variant={statusVariant(task)}>{statusLabel(task)}</Badge>}
      shortId={task.short_id}
      subtitle={note}
      title={task.title}
      to={to}
    />
  )
}
