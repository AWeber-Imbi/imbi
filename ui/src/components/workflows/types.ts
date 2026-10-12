import type { components } from '@/types/api-generated'

// Workflow API types (ADR 0021), from the generated OpenAPI schema.

/** A JSON Schema object. The API types `params_schema` as `dict[str, Any]`. */
export interface JsonSchema {
  $defs?: Record<string, JsonSchema>
  $ref?: string
  anyOf?: JsonSchema[]
  default?: unknown
  description?: string
  enum?: unknown[]
  items?: JsonSchema
  properties?: Record<string, JsonSchema>
  required?: string[]
  title?: string
  type?: string
}

export type StepCategory = StepType['category']

export type StepType = Omit<Schemas['StepType'], 'params_schema'> & {
  params_schema: JsonSchema
}
export type ValidationIssue = Schemas['ValidationIssue']
export type ValidationResult = Schemas['ValidationResult']
export type Workflow = Schemas['Workflow']
export type WorkflowEdge = Schemas['Edge']
export type WorkflowGraph = Schemas['Graph']
export type WorkflowNode = Schemas['Node']
export type WorkflowStatus = Schemas['WorkflowSummary']['status']
export type WorkflowSummary = Schemas['WorkflowSummary']

/** The body of a save; the editor always sends the graph and settings. */
export type WorkflowWrite = Required<Schemas['WorkflowSave']>

type Schemas = components['schemas']
