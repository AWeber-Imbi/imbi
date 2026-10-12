// Hand-written workflow API types (ADR 0021). Replace them with the
// generated OpenAPI types when the definitions API PR lands.

export type ConcurrencyMode = 'one_at_a_time' | 'one_per_key' | 'unlimited'

/** A JSON Schema object, as served in `params_schema`. */
export interface JsonSchema {
  default?: unknown
  description?: string
  enum?: unknown[]
  format?: string
  items?: JsonSchema
  properties?: Record<string, JsonSchema>
  required?: string[]
  title?: string
  type?: string | string[]
}

export type OnFailure = 'none' | 'notify_owner_team'

export type StepCategory = 'action' | 'agent' | 'logic' | 'trigger'

export interface StepType {
  category: StepCategory
  description: string
  idempotent: boolean
  label: string
  output_schema: JsonSchema
  params_schema: JsonSchema
  /** Null when the ports are `params.branches`. `[""]` is one unnamed port. */
  ports: null | string[]
  sample_output: unknown
  side_effect: boolean
  trigger: boolean
  type: string
}

export interface ValidationIssue {
  code: string
  edge_index: null | number
  message: string
  node_id: null | string
  severity: 'error' | 'warning'
}

export interface ValidationResult {
  issues: ValidationIssue[]
}

export interface Workflow extends WorkflowSummary {
  activated_at: null | string
  activated_by: null | string
  version: WorkflowVersion
}

export interface WorkflowEdge {
  port: number
  source: string
  target: string
}

export interface WorkflowGraph {
  edges: WorkflowEdge[]
  nodes: WorkflowNode[]
}

export interface WorkflowNode {
  id: string
  join: 'all' | 'any'
  key: string
  params: Record<string, unknown>
  position: { x: number; y: number }
  title: string
  type: string
}

export interface WorkflowSettings {
  concurrency_key: null | string
  concurrency_mode: ConcurrencyMode
  max_run_time_seconds: number
  on_failure: OnFailure
}

export type WorkflowStatus = 'active' | 'draft' | 'paused'

export interface WorkflowSummary {
  active_version: null | number
  agent_ids: string[]
  created_at: string
  description: string
  latest_version: number
  name: string
  owner_team_slug: string
  slug: string
  status: WorkflowStatus
  trigger_types: string[]
  updated_at: string
}

export interface WorkflowVersion {
  created_at: string
  created_by: string
  graph: WorkflowGraph
  settings: WorkflowSettings
  validation: ValidationResult
  version: number
}

export interface WorkflowWrite {
  description: string
  graph: WorkflowGraph
  name: string
  owner_team_slug: string
  settings: WorkflowSettings
}
