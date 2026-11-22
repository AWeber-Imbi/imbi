import type {
  TicketEvent,
  TicketListItem,
  TicketUnit,
  TicketUnitItem,
} from '@/types'

/** An event of T-1; `seq` also picks the time (12:00:<seq>). */
export function event(
  seq: number,
  type: string,
  payload: Record<string, unknown> = {},
  overrides: Partial<TicketEvent> = {},
): TicketEvent {
  return {
    actor_id: 'agt-1',
    actor_kind: 'agent',
    at: `2026-10-08T12:00:${String(seq).padStart(2, '0')}Z`,
    channel: 'harness',
    event_id: `00000000-0000-0000-0000-${String(seq).padStart(12, '0')}`,
    payload,
    schema_version: 1,
    seq,
    type,
    ...overrides,
  }
}

/** T-1 for Mender (agt-1), queued, owned by dev@example.com. */
export function task(overrides: Partial<TicketListItem> = {}): TicketListItem {
  return {
    agent_id: 'agt-1',
    agent_version: 3,
    assignee_kind: 'agent',
    blocked_since: null,
    budget: '5.000000',
    cache_read_tokens: 5000,
    cache_write_tokens: 800,
    closed_at: null,
    control: 'run',
    cost_total: '0.120000',
    created_at: '2026-10-08T12:00:00Z',
    custom_fields: {},
    description: 'Find why the build fails.',
    id: '00000000-0000-0000-0000-000000000001',
    labels: [],
    last_seq: 1,
    origin: { kind: 'human', user: 'dev@example.com' },
    owner: 'dev@example.com',
    phase: null,
    priority: 'normal',
    projects: [{ project_id: 'proj-1', project_slug: 'billing' }],
    prompt_version: 7,
    roles: {},
    service_account_id: 'agent-agt-1',
    short_id: 'T-1',
    status: 'queued',
    title: 'Fix the build',
    tokens_in: 1200,
    tokens_out: 300,
    type: 'task',
    updated_at: '2026-10-08T12:00:00Z',
    ...overrides,
  }
}

/** A ticket of a unit of work, queued, created at 12:00. */
export function unitItem(
  overrides: Partial<TicketUnitItem> = {},
): TicketUnitItem {
  return {
    agent_id: 'agt-1',
    closed_at: null,
    cost_total: '0.100000',
    created_at: '2026-10-08T12:00:00Z',
    nested: false,
    short_id: 'T-1',
    status: 'queued',
    title: 'Fix the build',
    ...overrides,
  }
}

/** A row of the run view: `rep` with the unit of `items`. */
export function unitRow(
  rep: TicketListItem,
  items: TicketUnitItem[],
  overrides: Partial<TicketUnit> = {},
): TicketListItem {
  return {
    ...rep,
    unit: {
      children: items.filter((i) => i.nested).length,
      cost_total: '1.000000',
      items,
      key: `ticket:${rep.id}`,
      last_activity_at: '2026-10-08T12:30:00Z',
      tickets: items.length,
      truncated: false,
      ...overrides,
    },
  }
}
