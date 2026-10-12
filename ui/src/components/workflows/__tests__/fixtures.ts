import type { StepType, Workflow, WorkflowNode } from '../types'

export const STEP_TYPES: StepType[] = [
  stepType({
    category: 'trigger',
    description: 'Started from Imbi',
    label: 'Manual run',
    params_schema: { properties: {}, type: 'object' },
    trigger: true,
    type: 'manual',
  }),
  stepType(),
  stepType({
    description: 'A model picks the branch',
    label: 'Model decision',
    params_schema: {
      properties: {
        branches: { items: { type: 'string' }, type: 'array' },
        prompt: { type: 'string' },
      },
      required: ['prompt'],
      type: 'object',
    },
    ports: null,
    type: 'model_decision',
  }),
  stepType({
    category: 'action',
    description: 'Ship a release',
    label: 'Deploy',
    ports: ['Succeeded', 'Failed'],
    type: 'deploy',
  }),
]

export const TYPES = Object.fromEntries(STEP_TYPES.map((t) => [t.type, t]))

export function node(overrides: Partial<WorkflowNode> = {}): WorkflowNode {
  return {
    id: 'n1',
    join: 'any',
    key: 'wait',
    params: {},
    position: { x: 0, y: 0 },
    title: 'Wait',
    type: 'wait',
    ...overrides,
  }
}

export function workflow(overrides: Partial<Workflow> = {}): Workflow {
  return {
    activated_at: null,
    activated_by: null,
    active_version: null,
    agent_ids: [],
    created_at: '2026-10-12T00:00:00Z',
    description: 'Ships and checks a deploy.',
    latest_version: 2,
    name: 'Deploy guard',
    owner_team_slug: 'platform',
    slug: 'deploy-guard',
    status: 'draft',
    trigger_types: ['manual'],
    updated_at: '2026-10-12T00:00:00Z',
    version: {
      created_at: '2026-10-12T00:00:00Z',
      created_by: 'gavin@example.com',
      graph: {
        edges: [{ port: 0, source: 'a', target: 'b' }],
        nodes: [
          node({ id: 'a', key: 'start', title: 'Start', type: 'manual' }),
          node({
            id: 'b',
            key: 'settle',
            position: { x: 320, y: 0 },
            title: 'Let traffic settle',
          }),
        ],
      },
      settings: {
        concurrency_key: null,
        concurrency_mode: 'unlimited',
        max_run_time_seconds: 3600,
        on_failure: 'notify_owner_team',
      },
      validation: { issues: [] },
      version: 2,
    },
    ...overrides,
  }
}

function stepType(overrides: Partial<StepType> = {}): StepType {
  return {
    category: 'logic',
    description: 'Pause for a time',
    idempotent: true,
    label: 'Wait',
    output_schema: {},
    params_schema: {
      properties: { duration: { default: '10m', type: 'string' } },
      required: ['duration'],
      type: 'object',
    },
    ports: [''],
    sample_output: {},
    side_effect: false,
    trigger: false,
    type: 'wait',
    ...overrides,
  }
}
