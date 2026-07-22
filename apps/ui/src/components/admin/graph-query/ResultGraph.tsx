import { useCallback, useMemo } from 'react'

import { darkTheme, GraphCanvas, lightTheme } from 'reagraph'
import type { GraphEdge, GraphNode, InternalGraphEdge } from 'reagraph'
import type { InternalGraphNode } from 'reagraph'

import { useTheme } from '@/contexts/ThemeContext'
import { inspectEdge, inspectNode } from '@/lib/graphInspection'
import type {
  GraphQueryEdge,
  GraphQueryInspection,
  GraphQueryNode,
  GraphQueryResult,
} from '@/types'

interface ResultGraphProps {
  onInspect: (item: GraphQueryInspection) => void
  result: GraphQueryResult
}

export function ResultGraph({ onInspect, result }: ResultGraphProps) {
  const { isDarkMode } = useTheme()

  const nodes = useMemo<GraphNode[]>(
    () =>
      result.nodes.map((n) => {
        const props = n.properties as Record<string, unknown>
        const labelText =
          (typeof props.name === 'string' && props.name) ||
          (typeof props.title === 'string' && props.title) ||
          (typeof props.slug === 'string' && props.slug) ||
          n.id
        return {
          data: n,
          fill: nodeColor(n.labels, isDarkMode),
          id: n.id,
          label: String(labelText),
        }
      }),
    [result.nodes, isDarkMode],
  )

  const edges = useMemo<GraphEdge[]>(
    () =>
      result.edges.map((e) => ({
        data: e,
        id: e.id,
        label: e.type,
        source: e.start,
        target: e.end,
      })),
    [result.edges],
  )

  const handleNodeClick = useCallback(
    (node: InternalGraphNode) =>
      onInspect(inspectNode(node.data as GraphQueryNode)),
    [onInspect],
  )

  const handleEdgeClick = useCallback(
    (edge: InternalGraphEdge) =>
      onInspect(inspectEdge(edge.data as GraphQueryEdge)),
    [onInspect],
  )

  if (nodes.length === 0) {
    return (
      <div className="text-tertiary flex h-full items-center justify-center text-xs">
        No graph data in this result.
      </div>
    )
  }

  return (
    <div className="relative size-full">
      <GraphCanvas
        cameraMode="pan"
        draggable
        edgeArrowPosition="end"
        edges={edges}
        labelType="nodes"
        layoutType="forceDirected2d"
        nodes={nodes}
        onEdgeClick={handleEdgeClick}
        onNodeClick={handleNodeClick}
        theme={isDarkMode ? darkTheme : lightTheme}
      />
    </div>
  )
}

function hashHue(value: string): number {
  let h = 0
  for (let i = 0; i < value.length; i++) {
    h = (h * 31 + value.charCodeAt(i)) >>> 0
  }
  return h % 360
}

// Keep a distinct hue per label, but tune lightness/saturation to the active
// theme so every hue stays legible: deeper on the light (#fff) background,
// brighter on the dark (#1E2026) background. Empty-label nodes fall back to
// the same slate the projects graph uses. NOTE: reagraph passes fills to
// three.js, whose color parser only understands comma-separated hsl() — the
// space-separated CSS form silently renders white, so keep the commas.
function nodeColor(labels: string[], isDarkMode: boolean): string {
  if (labels.length === 0) return '#64748b'
  const hue = hashHue(labels[0])
  return isDarkMode ? `hsl(${hue}, 60%, 64%)` : `hsl(${hue}, 58%, 42%)`
}
