import type {
  Agent,
  AgentToolCatalog,
  AgentUsage,
  PromptVersion,
} from '@/types'

export function agent(overrides: Partial<Agent> = {}): Agent {
  return {
    created_at: '2026-10-01T12:00:00Z',
    description: 'Fixes Sentry issues.',
    enabled: true,
    icon: null,
    id: 'agt-1',
    last_version_at: '2026-10-02T12:00:00Z',
    name: 'Mender',
    organization: { name: 'Acme', slug: 'acme' },
    prompt_ref: 'agents/mender@stable',
    prompt_version: 7,
    settings: {
      max_concurrent_tasks: 3,
      monthly_cost_cap: '400.00',
      response_sla: '4h',
      task_budget: '5.00',
      task_timeout_seconds: 1800,
    },
    slack_channel: '#cs-escalations',
    slug: 'mender',
    subagents: [],
    tags: [{ color: '#5A89C9', name: 'Routing', slug: 'routing' }],
    team: { name: 'Platform', slug: 'platform' },
    tools: {},
    updated_by: 'gavin@example.com',
    version: 3,
    ...overrides,
  }
}

export function catalog(): AgentToolCatalog {
  return {
    generated_at: '2026-10-06T12:00:00Z',
    groups: [
      {
        server: { name: 'Imbi', slug: 'imbi', transport: 'internal' },
        tools: [
          {
            capability: 'destructive',
            description: 'Delete a project.',
            key: 'imbi.delete_project',
            name: 'delete_project',
          },
          {
            capability: 'read',
            description: 'Search the service catalog.',
            key: 'imbi.list_projects',
            name: 'list_projects',
          },
        ],
      },
      {
        server: { name: 'GitHub', slug: 'github', transport: 'mcp/http' },
        tools: [
          {
            capability: 'write',
            description: 'Open a pull request.',
            key: 'github.create_pull_request',
            name: 'create_pull_request',
          },
          {
            capability: 'unknown',
            description: 'Read a file at a ref.',
            key: 'github.read_file',
            name: 'read_file',
          },
        ],
      },
      {
        error: 'timeout',
        server: { name: 'Sentry', slug: 'sentry', transport: 'mcp/http' },
        tools: [],
      },
    ],
  }
}

export function promptVersion(
  overrides: Partial<PromptVersion> = {},
): PromptVersion {
  return {
    content_sha256: 'abc',
    created_at: '2026-10-02T12:00:00Z',
    created_by: 'gavin@example.com',
    id: 'pv-2',
    labels: ['stable'],
    messages: [{ content: 'Hello', role: 'user' }],
    model: 'claude-sonnet',
    n: 2,
    params: {
      max_tokens: 8192,
      stop_sequences: ['END'],
      temperature: 0.5,
      top_k: 40,
    },
    questions: {},
    ref: 'agents/mender@2',
    state: '',
    system: 'You fix bugs.',
    tools: [],
    variable_schema: {},
    ...overrides,
  }
}

/** Mender (agt-1): 5 tasks, $12.50, 85% of its $400 monthly cap. */
export function usage(overrides: Partial<AgentUsage> = {}): AgentUsage {
  const totals = {
    agent_id: 'agt-1',
    cache_read_tokens: 3000,
    cache_write_tokens: 0,
    cost: '12.500000',
    tasks: 5,
    tokens_in: 1000,
    tokens_out: 400,
  }
  return {
    agents: [totals],
    days: [
      { ...totals, cost: '10.000000', day: '2026-10-07', tasks: 3 },
      { ...totals, cost: '2.500000', day: '2026-10-08', tasks: 2 },
    ],
    end: '2026-10-08',
    month_to_date: { 'agt-1': '340.000000' },
    start: '2026-09-09',
    unpriced_reports: 0,
    ...overrides,
  }
}
