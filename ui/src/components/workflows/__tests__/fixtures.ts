import type { StepType, Workflow, WorkflowNode, WorkflowRun } from '../types'

export const RUN: WorkflowRun = {
  cancel_requested: false,
  closed_at: null,
  created_at: '2026-10-12T00:00:00Z',
  dedupe_key: null,
  duplicate_of: null,
  error: null,
  id: '3f1c2a9e-0000-4000-8000-000000000001',
  log_archived_at: null,
  origin: {},
  origin_id: 'gavin@example.com',
  origin_kind: 'human',
  payload: {},
  started_at: null,
  status: 'queued',
  trigger_node_id: 'a',
  version: 2,
}

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
  stepType({
    category: 'agent',
    description: 'Gives an agent a task and waits for its outcome.',
    label: 'Agent task',
    params_schema: {
      properties: {
        agent_id: { type: 'string' },
        instruction: { type: 'string' },
      },
      required: ['agent_id', 'instruction'],
      type: 'object',
    },
    ports: ['Succeeded', 'Failed'],
    type: 'agent',
  }),
]

const CONDITION_VALUE = {
  anyOf: [
    { type: 'string' },
    { type: 'integer' },
    { type: 'number' },
    { type: 'boolean' },
    { items: {}, type: 'array' },
    { type: 'object' },
    { type: 'null' },
  ],
}

export const CONDITION: StepType = stepType({
  description: 'Compares values and takes the True or the False port.',
  label: 'Condition',
  params_schema: {
    $defs: {
      Condition: {
        properties: {
          a: CONDITION_VALUE,
          b: { ...CONDITION_VALUE, default: null },
          operator: {
            enum: ['equals', 'greater_than', 'is_empty'],
            type: 'string',
          },
        },
        required: ['a', 'operator'],
        type: 'object',
      },
    },
    properties: {
      conditions: {
        items: { $ref: '#/$defs/Condition' },
        type: 'array',
      },
      ignore_case: { default: false, type: 'boolean' },
      match: { default: 'all', enum: ['all', 'any'], type: 'string' },
    },
    required: ['conditions'],
    type: 'object',
  },
  ports: ['True', 'False'],
  type: 'condition',
})

/** The script step's schema, as Pydantic writes it (ADR 0027). */
export const SCRIPT: StepType = stepType({
  description: 'Runs Python in a sandbox and returns a structured result.',
  label: 'Script',
  params_schema: {
    $defs: {
      OutputField: {
        properties: { name: { type: 'string' }, type: { type: 'string' } },
        required: ['name', 'type'],
        type: 'object',
      },
    },
    properties: {
      branches: { default: [], items: { type: 'string' }, type: 'array' },
      code: { type: 'string' },
      inputs: { default: {}, type: 'object' },
      output_fields: {
        items: { $ref: '#/$defs/OutputField' },
        type: 'array',
      },
    },
    required: ['code', 'output_fields'],
    type: 'object',
  },
  ports: null,
  type: 'script',
})

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

export function stepType(overrides: Partial<StepType> = {}): StepType {
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
    retries: 0,
    sample_output: {},
    side_effect: false,
    timeout_seconds: null,
    trigger: false,
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
    bindings: [],
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
        dedupe_key: null,
        dedupe_window_seconds: null,
        max_run_time_seconds: 3600,
        on_failure: 'notify_owner_team',
      },
      validation: { issues: [] },
      version: 2,
    },
    ...overrides,
  }
}
