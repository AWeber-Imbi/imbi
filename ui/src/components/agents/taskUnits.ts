import type { TicketUnit, TicketUnitItem } from '@/types'

import { type InboxGroupId, statusVariant } from './taskEvents'

/** The status words that the group header already says. */
export const GROUP_SAYS: Partial<Record<InboxGroupId, string>> = {
  input: 'Needs input',
  paused: 'Paused',
  queued: 'Queued',
  running: 'Running',
}

const BAR_CLASSES: Record<ReturnType<typeof statusVariant>, string> = {
  danger: 'bg-(--ds-border-danger)',
  info: 'bg-(--ds-border-info)',
  neutral: 'bg-(--ds-border-secondary)',
  success: 'bg-(--ds-border-success)',
  warning: 'bg-(--ds-border-warning)',
}

/** The bar color of a ticket of a unit: its badge color, lighter for
 * a ticket that closed with nothing to do. */
export function barClass(item: TicketUnitItem): string {
  if (item.status === 'closed' && item.outcome === 'done_nothing_to_act_on')
    return 'bg-(--ds-border-success)/40'
  return BAR_CLASSES[statusVariant(item)]
}

/** The descendants of each top-level ticket of a unit, oldest first. */
export function treeOf(items: TicketUnitItem[]) {
  const children = new Map<string, TicketUnitItem[]>()
  for (const item of items)
    if (!isRoot(item, items) && item.parent_short_id)
      children.set(item.parent_short_id, [
        ...(children.get(item.parent_short_id) ?? []),
        item,
      ])
  const below = (id: string): TicketUnitItem[] =>
    (children.get(id) ?? []).flatMap((c) => [c, ...below(c.short_id)])
  return items
    .filter((i) => isRoot(i, items))
    .map((top) => ({
      descendants: below(top.short_id).sort((a, b) =>
        a.created_at.localeCompare(b.created_at),
      ),
      top,
    }))
}

/**
 * The title of a unit: what its run is about (a Jira key), else the
 * shared prefix of its tickets' titles, else its workflow's name, else
 * the title of its first ticket.
 */
export function unitTitle(unit: TicketUnit, fallback: string): string {
  const top = unit.items.filter((i) => isRoot(i, unit.items))
  return (
    unit.subject ??
    (top.length > 1 ? sharedPrefix(top.map((i) => i.title)) : undefined) ??
    unit.workflow_name ??
    top[0]?.title ??
    fallback
  )
}

/**
 * Whether a ticket is a top-level row of its unit: its parent is not in
 * the unit, or not in `items`, which a large unit truncates.
 */
function isRoot(item: TicketUnitItem, items: TicketUnitItem[]): boolean {
  return !item.nested || !items.some((i) => i.short_id === item.parent_short_id)
}

/** The text before `: ` that every title has, if they all share one. */
function sharedPrefix(titles: string[]): string | undefined {
  const prefixes = titles.map((t) => t.split(': ')[0] ?? '')
  const first = prefixes[0]
  return first &&
    titles.every((t) => t.includes(': ')) &&
    prefixes.every((p) => p === first)
    ? first
    : undefined
}
