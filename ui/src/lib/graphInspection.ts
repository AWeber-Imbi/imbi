import type {
  GraphQueryCell,
  GraphQueryCellEdge,
  GraphQueryCellNode,
  GraphQueryEdge,
  GraphQueryInspection,
  GraphQueryNode,
} from '@/types'

/** Build a drawer inspection for a graph edge. */
export function inspectEdge(
  edge: GraphQueryCellEdge | GraphQueryEdge,
): GraphQueryInspection {
  return {
    entries: Object.entries(edge.properties),
    heading: `[:${edge.type}]`,
    id: edge.id,
    kind: 'edge',
  }
}

/** Build a drawer inspection for a graph node. */
export function inspectNode(
  node: GraphQueryCellNode | GraphQueryNode,
): GraphQueryInspection {
  return {
    entries: Object.entries(node.properties),
    heading: node.labels.length ? `:${node.labels.join(':')}` : 'Node',
    id: node.id,
    kind: 'node',
  }
}

/**
 * Build a drawer inspection for a table row. A single-column row whose value
 * is a node or edge inspects that element directly (the common
 * ``RETURN p`` case); anything else lists the row's columns.
 */
export function inspectRow(
  columns: string[],
  row: Record<string, GraphQueryCell>,
): GraphQueryInspection {
  if (columns.length === 1) {
    const only = row[columns[0]]
    if (isNodeCell(only)) return inspectNode(only)
    if (isEdgeCell(only)) return inspectEdge(only)
  }
  return {
    entries: columns.map((col) => [col, row[col]]),
    heading: 'Row',
    kind: 'row',
  }
}

function isEdgeCell(cell: GraphQueryCell): cell is GraphQueryCellEdge {
  return (
    typeof cell === 'object' &&
    cell !== null &&
    !Array.isArray(cell) &&
    (cell as { _kind?: string })._kind === 'edge'
  )
}

function isNodeCell(cell: GraphQueryCell): cell is GraphQueryCellNode {
  return (
    typeof cell === 'object' &&
    cell !== null &&
    !Array.isArray(cell) &&
    (cell as { _kind?: string })._kind === 'node'
  )
}
