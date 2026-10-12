import type {
  JsonSchema,
  StepType,
  WorkflowEdge,
  WorkflowGraph,
  WorkflowNode,
} from './types'

// Pure graph and canvas math for the workflow editor. Components hold
// the state; these functions compute every change, so tests can cover
// them without a DOM.

export interface Point {
  x: number
  y: number
}

export interface View {
  x: number
  y: number
  zoom: number
}

export const NODE_W = 248
export const GRID = 20
const HEAD_H = 56
const SUMMARY_H = 36
const ROW_H = 30
const ROWS_PAD = 4
const MIN_ZOOM = 0.25
const MAX_ZOOM = 2

/** A new node's branches when its type takes ports from `params.branches`. */
const DEFAULT_BRANCHES = ['Yes', 'No']

export type StepTypes = Record<string, StepType>

/** Add `node` and, when `from` is set and the node is not a trigger, an edge into it. */
export function addNode(
  graph: WorkflowGraph,
  node: WorkflowNode,
  types: StepTypes,
  from?: { port: number; source: string },
): WorkflowGraph {
  const next = { ...graph, nodes: [...graph.nodes, node] }
  if (!from) return next
  return connect(next, types, { ...from, target: node.id })
}

export function canConnect(
  graph: WorkflowGraph,
  types: StepTypes,
  edge: WorkflowEdge,
): boolean {
  const target = graph.nodes.find((n) => n.id === edge.target)
  if (!target || edge.source === edge.target) return false
  if (types[target.type]?.trigger) return false
  return !graph.edges.some(
    (e) =>
      e.source === edge.source &&
      e.port === edge.port &&
      e.target === edge.target,
  )
}

export function connect(
  graph: WorkflowGraph,
  types: StepTypes,
  edge: WorkflowEdge,
): WorkflowGraph {
  if (!canConnect(graph, types, edge)) return graph
  return { ...graph, edges: [...graph.edges, edge] }
}

export function createNode(
  graph: WorkflowGraph,
  type: StepType,
  position: Point,
): WorkflowNode {
  const params = defaultParams(type.params_schema)
  if (type.ports === null && !Array.isArray(params.branches)) {
    params.branches = [...DEFAULT_BRANCHES]
  }
  return {
    id: crypto.randomUUID(),
    join: 'any',
    key: uniqueKey(graph, keyFromTitle(type.label)),
    params,
    position: { x: snap(position.x), y: snap(position.y) },
    title: type.label,
    type: type.type,
  }
}

export function duplicateNode(
  graph: WorkflowGraph,
  id: string,
): { graph: WorkflowGraph; node: null | WorkflowNode } {
  const source = graph.nodes.find((n) => n.id === id)
  if (!source) return { graph, node: null }
  const title = `${source.title} copy`
  const node: WorkflowNode = {
    ...structuredClone(source),
    id: crypto.randomUUID(),
    key: uniqueKey(graph, keyFromTitle(title)),
    position: { x: source.position.x + 40, y: source.position.y + 120 },
    title,
  }
  return { graph: { ...graph, nodes: [...graph.nodes, node] }, node }
}

/** A cubic bezier from an output port to an input port, and its midpoint. */
export function edgePath(a: Point, b: Point): Point & { d: string } {
  const c = Math.max(60, Math.abs(b.x - a.x) * 0.5) * (b.x < a.x ? 1.6 : 1)
  return {
    d: `M${a.x} ${a.y} C${a.x + c} ${a.y} ${b.x - c} ${b.y} ${b.x} ${b.y}`,
    x: (a.x + 3 * (a.x + c) + 3 * (b.x - c) + b.x) / 8,
    y: (a.y + b.y) / 2,
  }
}

/** The view that shows every node, at 100% or less. */
export function fitView(
  graph: WorkflowGraph,
  types: StepTypes,
  width: number,
  height: number,
): View {
  if (graph.nodes.length === 0) return { x: width / 2, y: height / 2, zoom: 1 }
  let x0 = Infinity
  let y0 = Infinity
  let x1 = -Infinity
  let y1 = -Infinity
  for (const n of graph.nodes) {
    x0 = Math.min(x0, n.position.x)
    y0 = Math.min(y0, n.position.y)
    x1 = Math.max(x1, n.position.x + NODE_W)
    y1 = Math.max(y1, n.position.y + nodeHeight(portsOf(n, types)))
  }
  const pad = 64
  const zoom = Math.max(
    0.3,
    Math.min(1, (width - pad * 2) / (x1 - x0), (height - pad * 2) / (y1 - y0)),
  )
  return {
    x: (width - (x1 - x0) * zoom) / 2 - x0 * zoom,
    y: (height - (y1 - y0) * zoom) / 2 - y0 * zoom,
    zoom,
  }
}

export function inPoint(node: WorkflowNode): Point {
  return { x: node.position.x, y: node.position.y + HEAD_H / 2 }
}

export function isSinglePort(ports: string[]): boolean {
  return ports.length === 1 && ports[0] === ''
}

/** A node key from a title: lower case, `_` separators, starts with a letter. */
export function keyFromTitle(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
  if (!slug) return 'step'
  return /^[a-z]/.test(slug) ? slug : `step_${slug}`
}

export function outPoint(
  node: WorkflowNode,
  ports: string[],
  index: number,
): Point {
  const x = node.position.x + NODE_W
  if (isSinglePort(ports)) return { x, y: node.position.y + HEAD_H / 2 }
  return {
    x,
    y:
      node.position.y +
      HEAD_H +
      SUMMARY_H +
      ROWS_PAD +
      ROW_H * index +
      ROW_H / 2,
  }
}

/**
 * Where a palette click puts a new node: right of the selected node,
 * level with its first free port, or the canvas centre. It moves down
 * until it does not cover another node.
 */
export function placeNew(
  graph: WorkflowGraph,
  types: StepTypes,
  center: Point,
  selected: null | WorkflowNode,
  trigger: boolean,
): { from?: { port: number; source: string }; position: Point } {
  let position: Point = { x: center.x - NODE_W / 2, y: center.y - 47 }
  let from: undefined | { port: number; source: string }
  if (selected && !trigger) {
    const ports = portsOf(selected, types)
    const used = new Set(
      graph.edges.filter((e) => e.source === selected.id).map((e) => e.port),
    )
    const port = Math.max(
      0,
      ports.findIndex((_, i) => !used.has(i)),
    )
    if (ports.length > 0) from = { port, source: selected.id }
    position = {
      x: selected.position.x + 320,
      y: outPoint(selected, ports, port).y - HEAD_H / 2,
    }
  }
  for (
    let guard = 0;
    guard < 20 &&
    graph.nodes.some(
      (n) =>
        Math.abs(n.position.x - position.x) < NODE_W &&
        Math.abs(n.position.y - position.y) < 100,
    );
    guard++
  ) {
    position = { ...position, y: position.y + 120 }
  }
  return { from, position }
}

/** The output port labels of a node. `[""]` is one unnamed port. */
export function portsOf(node: WorkflowNode, types: StepTypes): string[] {
  const type = types[node.type]
  if (!type) return ['']
  if (type.ports !== null) return type.ports
  const branches = node.params.branches
  return Array.isArray(branches) ? branches.map(String) : []
}

/** Remove branch `index`: drop its edges and move higher ports down one. */
export function removeBranch(
  graph: WorkflowGraph,
  id: string,
  index: number,
): WorkflowGraph {
  return {
    edges: graph.edges
      .filter((e) => !(e.source === id && e.port === index))
      .map((e) =>
        e.source === id && e.port > index ? { ...e, port: e.port - 1 } : e,
      ),
    nodes: graph.nodes.map((n) => {
      if (n.id !== id || !Array.isArray(n.params.branches)) return n
      const branches = n.params.branches.filter((_, i) => i !== index)
      return { ...n, params: { ...n.params, branches } }
    }),
  }
}

export function removeEdge(graph: WorkflowGraph, index: number): WorkflowGraph {
  return { ...graph, edges: graph.edges.filter((_, i) => i !== index) }
}

/** Remove a node and every edge into or out of it. */
export function removeNode(graph: WorkflowGraph, id: string): WorkflowGraph {
  return {
    edges: graph.edges.filter((e) => e.source !== id && e.target !== id),
    nodes: graph.nodes.filter((n) => n.id !== id),
  }
}

export function snap(value: number): number {
  return Math.round(value / GRID) * GRID
}

/** A client (screen) point in canvas coordinates. */
export function toCanvas(client: Point, origin: Point, view: View): Point {
  return {
    x: (client.x - origin.x - view.x) / view.zoom,
    y: (client.y - origin.y - view.y) / view.zoom,
  }
}

/** `base`, or `base_2`, `base_3`, … when another node has the key. */
export function uniqueKey(
  graph: WorkflowGraph,
  base: string,
  exceptId?: string,
): string {
  const taken = new Set(
    graph.nodes.filter((n) => n.id !== exceptId).map((n) => n.key),
  )
  if (!taken.has(base)) return base
  let i = 2
  while (taken.has(`${base}_${i}`)) i++
  return `${base}_${i}`
}

export function updateNode(
  graph: WorkflowGraph,
  id: string,
  patch: Partial<WorkflowNode>,
): WorkflowGraph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) => (n.id === id ? { ...n, ...patch } : n)),
  }
}

/** Zoom by `factor` and keep the canvas point under `at` (viewport coordinates) still. */
export function zoomAt(view: View, at: Point, factor: number): View {
  const zoom = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, view.zoom * factor))
  return {
    x: at.x - ((at.x - view.x) * zoom) / view.zoom,
    y: at.y - ((at.y - view.y) * zoom) / view.zoom,
    zoom,
  }
}

function defaultParams(schema: JsonSchema): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  for (const [name, prop] of Object.entries(schema.properties ?? {})) {
    if (prop.default !== undefined) params[name] = structuredClone(prop.default)
  }
  return params
}

function nodeHeight(ports: string[]): number {
  if (isSinglePort(ports)) return HEAD_H + SUMMARY_H
  return HEAD_H + SUMMARY_H + ROWS_PAD * 2 + ROW_H * ports.length
}
