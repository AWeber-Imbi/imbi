import { useRef, useState, useMemo, useCallback, useEffect } from 'react'
import {
  GraphCanvas,
  GraphCanvasRef,
  LayoutTypes,
  lightTheme,
  darkTheme,
  useSelection,
} from 'reagraph'
import type { GraphEdge, InternalGraphNode } from 'reagraph'
import {
  ZoomIn,
  ZoomOut,
  Maximize2,
  ChevronDown,
  Expand,
  Shrink,
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useTheme } from '@/contexts/ThemeContext'
import { Card, CardHeader, CardContent } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { getIconUrl } from '@/lib/icons'
import {
  EDGE_COLOR_DEPENDS_ON,
  EDGE_COLOR_DEPENDED_UPON,
} from '@/lib/relationship-edges'

export interface GraphProject {
  id: string
  name: string
  project_types?: {
    slug: string
    icon?: string | null
  }[]
}

const LAYOUT_OPTIONS: { label: string; value: LayoutTypes }[] = [
  { label: 'Force Directed', value: 'forceDirected2d' },
  { label: 'Circular', value: 'circular2d' },
  { label: 'Radial Out', value: 'radialOut2d' },
  { label: 'Force Atlas', value: 'forceatlas2' },
  { label: 'Concentric', value: 'concentric2d' },
]

// Camera distance at which node labels are comfortably legible.
// Increase to zoom out further at 100%, decrease to zoom in closer.
const ZOOM_100_DISTANCE = 1800

/** Returns the IDs of the largest connected component in the graph. */
function largestComponent(
  nodeIds: string[],
  edges: { source: string; target: string }[],
): string[] {
  const adj = new Map<string, Set<string>>()
  for (const id of nodeIds) adj.set(id, new Set())
  for (const e of edges) {
    adj.get(e.source)?.add(e.target)
    adj.get(e.target)?.add(e.source)
  }
  const visited = new Set<string>()
  let best: string[] = []
  for (const start of nodeIds) {
    if (visited.has(start)) continue
    const component: string[] = []
    const queue = [start]
    while (queue.length) {
      const node = queue.pop()!
      if (visited.has(node)) continue
      visited.add(node)
      component.push(node)
      for (const neighbor of adj.get(node) ?? []) {
        if (!visited.has(neighbor)) queue.push(neighbor)
      }
    }
    if (component.length > best.length) best = component
  }
  return best
}

interface ProjectsGraphCanvasProps {
  projects: GraphProject[]
  edges: GraphEdge[]
  centerId?: string
}

export function ProjectsGraphCanvas({
  projects,
  edges,
  centerId,
}: ProjectsGraphCanvasProps) {
  const navigate = useNavigate()
  const { isDarkMode } = useTheme()
  const ref = useRef<GraphCanvasRef | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [layout, setLayoutState] = useState<LayoutTypes>(() => {
    const stored = localStorage.getItem('imbi-graph-layout')
    const valid = LAYOUT_OPTIONS.some((o) => o.value === stored)
    return valid ? (stored as LayoutTypes) : 'forceDirected2d'
  })
  const setLayout = (v: LayoutTypes) => {
    localStorage.setItem('imbi-graph-layout', v)
    setLayoutState(v)
  }
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [currentZoom, setCurrentZoom] = useState(100)
  const [isRendering, setIsRendering] = useState(true)

  // Stable key that forces GraphCanvas to remount when layout or node set changes.
  const graphKey = useMemo(() => {
    const ids = projects
      .map((p) => p.id)
      .sort()
      .join('|')
    let h = 5381
    for (let i = 0; i < ids.length; i++)
      h = (((h << 5) + h) ^ ids.charCodeAt(i)) >>> 0
    return `${layout}-${h}`
  }, [layout, projects])

  // Track fullscreen state from browser events (handles Escape key exit too)
  useEffect(() => {
    const handleFsChange = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', handleFsChange)
    return () =>
      document.removeEventListener('fullscreenchange', handleFsChange)
  }, [])

  // Fit all nodes in view after layout settles.
  useEffect(() => {
    if (projects.length === 0) return
    setIsRendering(true)
    const clusterIds = largestComponent(
      nodes.map((n) => n.id),
      edges,
    )
    const fitTimer = setTimeout(() => {
      ref.current?.centerGraph()
      ref.current?.fitNodesInView(
        clusterIds.length > 1 ? clusterIds : undefined,
      )
      setIsRendering(false)
    }, 1200)

    // After fit settles, capture reference distance (= 100%) and start tracking.
    let removeListener: (() => void) | undefined
    const listenTimer = setTimeout(() => {
      const controls = ref.current?.getControls() ?? null
      if (!controls) return
      setCurrentZoom(Math.round((ZOOM_100_DISTANCE / controls.distance) * 100))
      const onUpdate = () => {
        const next = Math.round((ZOOM_100_DISTANCE / controls.distance) * 100)
        setCurrentZoom((prev) => (prev === next ? prev : next))
      }
      controls.addEventListener('update', onUpdate)
      removeListener = () => controls.removeEventListener('update', onUpdate)
    }, 700)

    return () => {
      clearTimeout(fitTimer)
      clearTimeout(listenTimer)
      removeListener?.()
    }
    // graphKey already encodes layout + node set
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphKey])

  const toggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      containerRef.current?.requestFullscreen()
    } else {
      document.exitFullscreen()
    }
  }, [])

  // Map each node to its edge color for icon tinting
  const nodeEdgeColor = useMemo(() => {
    const map = new Map<string, string>()
    for (const e of edges) {
      if (!map.has(e.source)) map.set(e.source, e.fill ?? '')
      if (!map.has(e.target)) map.set(e.target, e.fill ?? '')
    }
    return map
  }, [edges])

  const nodes = useMemo(
    () =>
      projects.map((p) => {
        const isCenter = centerId && p.id === centerId
        const iconColor = isCenter
          ? '#f59e0b'
          : nodeEdgeColor.get(p.id) || undefined
        const iconUrl = getIconUrl(
          (p.project_types || [])[0]?.icon ?? null,
          iconColor,
        )
        const fill = isCenter ? '#f59e0b' : '#64748b'
        return {
          id: p.id,
          label: p.name,
          fill,
          ...(iconUrl ? { icon: iconUrl } : {}),
          data: p,
        }
      }),
    [projects, centerId, nodeEdgeColor],
  )

  const {
    selections,
    actives,
    onNodeClick: selectNode,
    onCanvasClick,
  } = useSelection({
    ref,
    nodes,
    edges,
    type: 'single',
    pathSelectionType: 'all',
    focusOnSelect: false,
  })

  const handleNodeClick = useCallback(
    (node: InternalGraphNode) => selectNode?.(node),
    [selectNode],
  )

  const handleNodeDoubleClick = useCallback(
    (node: InternalGraphNode) => {
      const p = node.data as GraphProject
      navigate(`/projects/${p.id}`)
    },
    [navigate],
  )

  const currentLayoutLabel =
    LAYOUT_OPTIONS.find((l) => l.value === layout)?.label ??
    LAYOUT_OPTIONS[0].label

  const btnClass = ''

  return (
    <div
      ref={containerRef}
      className={isFullscreen ? 'flex h-screen flex-col' : 'h-full'}
    >
      <Card
        className={`flex flex-col overflow-hidden ${
          isFullscreen ? 'h-full rounded-none border-0' : 'h-full'
        } `}
      >
        {/* Toolbar */}
        <CardHeader
          className={`flex-shrink-0 flex-row items-center gap-2 space-y-0 border-b border-tertiary px-4 py-3`}
        >
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="sm"
                className={`gap-2 ${btnClass}`}
              >
                {currentLayoutLabel}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {LAYOUT_OPTIONS.map((opt) => (
                <DropdownMenuItem
                  key={opt.value}
                  className={layout === opt.value ? 'font-medium' : ''}
                  onClick={() => setLayout(opt.value)}
                >
                  {opt.label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>

          <div className="flex items-center gap-1">
            <Button
              variant="outline"
              size="sm"
              title="Zoom in"
              aria-label="Zoom in"
              onClick={() => ref.current?.zoomIn()}
              className={btnClass}
            >
              <ZoomIn className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              title="Zoom out"
              aria-label="Zoom out"
              onClick={() => ref.current?.zoomOut()}
              className={btnClass}
            >
              <ZoomOut className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              title="Reset to 100% zoom"
              disabled={currentZoom === 100}
              onClick={() =>
                ref.current?.getControls().dollyTo(ZOOM_100_DISTANCE, true)
              }
              className={btnClass}
            >
              {currentZoom}%
            </Button>
            <Button
              variant="outline"
              size="sm"
              title="Fit to view"
              aria-label="Fit to view"
              onClick={() => ref.current?.fitNodesInView()}
              className={btnClass}
            >
              <Maximize2 className="h-4 w-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
              onClick={toggleFullscreen}
              className={btnClass}
            >
              {isFullscreen ? (
                <Shrink className="h-4 w-4" />
              ) : (
                <Expand className="h-4 w-4" />
              )}
            </Button>
          </div>

          <div className="ml-auto flex items-center gap-4 text-xs text-tertiary">
            <span className="flex items-center gap-1">
              <span
                className="inline-block h-0.5 w-3 rounded-l"
                style={{ backgroundColor: EDGE_COLOR_DEPENDS_ON }}
              />
              <span
                className="inline-block"
                style={{
                  borderLeft: `5px solid ${EDGE_COLOR_DEPENDS_ON}`,
                  borderTop: '3px solid transparent',
                  borderBottom: '3px solid transparent',
                }}
              />
              Uses
            </span>
            <span className="flex items-center gap-1">
              <span
                className="inline-block h-0.5 w-3 rounded-l"
                style={{ backgroundColor: EDGE_COLOR_DEPENDED_UPON }}
              />
              <span
                className="inline-block"
                style={{
                  borderLeft: `5px solid ${EDGE_COLOR_DEPENDED_UPON}`,
                  borderTop: '3px solid transparent',
                  borderBottom: '3px solid transparent',
                }}
              />
              Used by
            </span>
            <span>
              {nodes.length} projects · {edges.length} relationships ·
              Double-click to open
            </span>
          </div>
        </CardHeader>

        {/* Canvas */}
        <CardContent
          className={`relative p-0 ${isFullscreen ? 'flex-1' : 'min-h-[400px] flex-1'}`}
        >
          {isRendering && nodes.length > 0 && (
            <div
              className={`absolute inset-0 z-10 flex items-center justify-center bg-background/80`}
            >
              <div className="flex flex-col items-center gap-3">
                <div className="h-8 w-8 animate-spin rounded-full border-2 border-current border-t-transparent opacity-50" />
                <p className="text-sm text-tertiary">Rendering graph…</p>
              </div>
            </div>
          )}
          {nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-tertiary">No projects to display</p>
            </div>
          ) : (
            <GraphCanvas
              key={graphKey}
              ref={ref}
              nodes={nodes}
              edges={edges}
              layoutType={layout}
              theme={isDarkMode ? darkTheme : lightTheme}
              labelType="nodes"
              edgeArrowPosition="end"
              selections={selections}
              actives={actives}
              draggable
              cameraMode="pan"
              onNodeClick={handleNodeClick}
              onCanvasClick={onCanvasClick}
              onNodeDoubleClick={handleNodeDoubleClick}
            />
          )}
        </CardContent>
      </Card>
    </div>
  )
}
