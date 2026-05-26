import { useMemo } from 'react'

import { darkTheme, GraphCanvas, lightTheme } from 'reagraph'
import type { GraphEdge, GraphNode } from 'reagraph'

import { useTheme } from '@/contexts/ThemeContext'
import type { GraphQueryResult } from '@/types'

interface ResultGraphProps {
  result: GraphQueryResult
}

export function ResultGraph({ result }: ResultGraphProps) {
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
          fill: nodeColor(n.labels),
          id: n.id,
          label: String(labelText),
        }
      }),
    [result.nodes],
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

function nodeColor(labels: string[]): string {
  if (labels.length === 0) return '#64748b'
  const hue = hashHue(labels[0])
  return `hsl(${hue} 55% 55%)`
}
