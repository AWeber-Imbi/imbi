import type { AgentTaskEvent, AgentTaskListItem } from '@/types'

/** An event of T-1; `seq` also picks the time (12:00:<seq>). */
export function event(
  seq: number,
  type: string,
  payload: Record<string, unknown> = {},
  overrides: Partial<AgentTaskEvent> = {},
): AgentTaskEvent {
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
export function task(
  overrides: Partial<AgentTaskListItem> = {},
): AgentTaskListItem {
  return {
    agent_id: 'agt-1',
    agent_version: 3,
    blocked_since: null,
    budget: '5.000000',
    cache_read_tokens: 5000,
    cache_write_tokens: 800,
    closed_at: null,
    control: 'run',
    cost_total: '0.120000',
    created_at: '2026-10-08T12:00:00Z',
    description: 'Find why the build fails.',
    id: '00000000-0000-0000-0000-000000000001',
    last_seq: 1,
    origin: { kind: 'human', user: 'dev@example.com' },
    owner: 'dev@example.com',
    phase: null,
    project_id: 'proj-1',
    project_slug: 'billing',
    prompt_version: 7,
    service_account_id: 'agent-agt-1',
    short_id: 'T-1',
    status: 'queued',
    title: 'Fix the build',
    tokens_in: 1200,
    tokens_out: 300,
    updated_at: '2026-10-08T12:00:00Z',
    ...overrides,
  }
}
