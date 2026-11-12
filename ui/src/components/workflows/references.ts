import type { StepTypes } from './graph'
import { type OutputField, typeLabel } from './outputFields'
import type { JsonSchema, WorkflowGraph, WorkflowNode } from './types'

export interface Reference {
  path: string
  type: string
}

export interface ReferenceGroup {
  key: string
  /** The step is not on every path from a trigger to the node. */
  mayNotRun: boolean
  references: Reference[]
  title: string
}

export function insertReference(
  value: string,
  path: string,
  selection: [number, number] | null,
): { caret: number; value: string } {
  const text = `{{ ${path} }}`
  const [start, end] = selection ?? [value.length, value.length]
  return {
    caret: start + text.length,
    value: value.slice(0, start) + text + value.slice(end),
  }
}

export function referenceGroups(
  graph: WorkflowGraph,
  types: StepTypes,
  nodeId: string,
): ReferenceGroup[] {
  const distances = ancestorDistances(graph, nodeId)
  const ancestors = graph.nodes.filter((node) => distances.has(node.id))
  const triggers = ancestors.filter((node) => types[node.type]?.trigger)
  const triggerIds = triggers.map((node) => node.id)
  const steps = ancestors
    .filter((node) => !types[node.type]?.trigger)
    .sort(
      (first, second) =>
        (distances.get(first.id) ?? 0) - (distances.get(second.id) ?? 0),
    )
    .map((node) => ({
      key: node.key,
      mayNotRun: reaches(graph, triggerIds, nodeId, node.id),
      references: stepReferences(
        node,
        types[node.type]?.output_schema,
        afterFailure(graph, node, types[node.type]?.ports ?? [], nodeId),
      ),
      title: node.title,
    }))
  if (triggers.length === 0) return steps
  return [
    ...steps,
    {
      key: 'trigger',
      mayNotRun: false,
      references: triggerReferences(triggers, types),
      title: 'Trigger',
    },
  ]
}

/** The node is reached through the step's `Failed` port, where an
 * agent step has no result. */
function afterFailure(
  graph: WorkflowGraph,
  step: WorkflowNode,
  ports: string[],
  nodeId: string,
): boolean {
  const port = ports.indexOf('Failed')
  const targets = graph.edges
    .filter((edge) => edge.source === step.id && edge.port === port)
    .map((edge) => edge.target)
  return reaches(graph, targets, nodeId, step.id)
}

function ancestorDistances(
  graph: WorkflowGraph,
  nodeId: string,
): Map<string, number> {
  const distances = new Map<string, number>()
  let frontier = [nodeId]
  for (let distance = 1; frontier.length > 0; distance++) {
    frontier = graph.edges
      .filter(
        (edge) =>
          frontier.includes(edge.target) &&
          edge.source !== nodeId &&
          !distances.has(edge.source),
      )
      .map((edge) => edge.source)
    for (const id of frontier) distances.set(id, distance)
  }
  return distances
}

/** A manual trigger's payload is its declared inputs. */
function manualInputs(node: WorkflowNode): Reference[] {
  const inputs = node.params.inputs
  if (!Array.isArray(inputs)) return []
  return (inputs as { name: string; type?: string }[]).map((input) => ({
    path: `trigger.${input.name}`,
    type: input.type ?? 'string',
  }))
}

function outputFieldsOf(node: WorkflowNode): OutputField[] {
  const fields = node.params.output_fields
  return Array.isArray(fields) ? (fields as OutputField[]) : []
}

function reaches(
  graph: WorkflowGraph,
  from: string[],
  target: string,
  blocked: string,
): boolean {
  const seen = new Set([blocked, ...from])
  const stack = [...from]
  for (let id = stack.pop(); id !== undefined; id = stack.pop()) {
    if (id === target) return true
    for (const edge of graph.edges) {
      if (edge.source === id && !seen.has(edge.target)) {
        seen.add(edge.target)
        stack.push(edge.target)
      }
    }
  }
  return false
}

function resultReferences(
  fields: OutputField[],
  prefix: string,
  nullable: boolean,
): Reference[] {
  return fields.flatMap((field) => {
    const path = `${prefix}.${field.name}`
    return [
      {
        path,
        type: typeLabel(nullable ? { ...field, required: false } : field),
      },
      ...(field.type === 'object'
        ? resultReferences(field.fields ?? [], path, nullable)
        : []),
    ]
  })
}

function schemaReferences(prefix: string, schema?: JsonSchema): Reference[] {
  return Object.entries(schema?.properties ?? {}).map(([name, property]) => ({
    path: `${prefix}.${name}`,
    type: schemaType(property),
  }))
}

function schemaType(schema: JsonSchema): string {
  if (schema.anyOf) return schema.anyOf.map(schemaType).join(' | ')
  if (schema.type === 'array') {
    return `array<${schema.items ? schemaType(schema.items) : 'any'}>`
  }
  return schema.type ?? (schema.$ref ? 'object' : 'any')
}

function stepReferences(
  node: WorkflowNode,
  schema: JsonSchema | undefined,
  failed: boolean,
): Reference[] {
  const fields = outputFieldsOf(node)
  return schemaReferences(node.key, schema).flatMap((reference) =>
    reference.path === `${node.key}.result`
      ? [reference, ...resultReferences(fields, reference.path, failed)]
      : [reference],
  )
}

function triggerReferences(
  triggers: WorkflowNode[],
  types: StepTypes,
): Reference[] {
  const references = triggers.flatMap((node) => [
    ...manualInputs(node),
    ...schemaReferences('trigger', types[node.type]?.output_schema),
  ])
  if (references.length === 0) return [{ path: 'trigger', type: 'object' }]
  return [
    ...new Map(
      references.map((reference) => [reference.path, reference]),
    ).values(),
  ]
}
