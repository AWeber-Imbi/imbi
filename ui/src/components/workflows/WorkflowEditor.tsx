import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { Link, useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowLeft, ChevronUp } from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  activateWorkflow,
  createWorkflow,
  pauseWorkflow,
  updateWorkflow,
  validateWorkflow,
} from '@/api/endpoints'
import { agentsPath } from '@/components/agents/agentsNav'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

import { Canvas, type Selection } from './Canvas'
import type { NodeSummary } from './CanvasNode'
import {
  addNode,
  connect,
  createNode,
  duplicateNode,
  fitView,
  placeNew,
  type Point,
  removeBranch,
  removeEdge,
  removeNode,
  type StepTypes,
  toCanvas,
  updateNode,
  type View,
} from './graph'
import { EdgePanel, NodePanel, SettingsPanel } from './Inspector'
import { Palette } from './Palette'
import { paramSummary } from './schemaFields'
import type {
  StepType,
  ValidationIssue,
  Workflow,
  WorkflowGraph,
  WorkflowWrite,
} from './types'
import { StatusBadge } from './WorkflowStatusBadge'

const NEW_SETTINGS: WorkflowWrite['settings'] = {
  concurrency_key: null,
  concurrency_mode: 'unlimited',
  max_run_time_seconds: 3600,
  on_failure: 'notify_owner_team',
}

interface WorkflowEditorProps {
  orgSlug: string
  stepTypes: StepType[]
  /** Null for a workflow that is not created yet. */
  workflow: null | Workflow
}

/** The canvas editor for one workflow: header, palette, canvas, inspector. */
export function WorkflowEditor({
  orgSlug,
  stepTypes,
  workflow,
}: WorkflowEditorProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canWrite = useHasPermission(
    workflow ? 'workflow:write' : 'workflow:create',
  )
  const readOnly = !canWrite
  const types: StepTypes = useMemo(
    () => Object.fromEntries(stepTypes.map((t) => [t.type, t])),
    [stepTypes],
  )
  const [current, setCurrent] = useState(workflow)
  const [draft, setDraft] = useState<WorkflowWrite>(() => ({
    description: workflow?.description ?? '',
    graph: workflow?.version.graph ?? { edges: [], nodes: [] },
    name: workflow?.name ?? 'Untitled workflow',
    owner_team_slug: workflow?.owner_team_slug ?? '',
    settings: workflow?.version.settings ?? NEW_SETTINGS,
  }))
  const [dirty, setDirty] = useState(false)
  const [selection, setSelection] = useState<Selection>(null)
  const [paletteOpen, setPaletteOpen] = useState(true)
  const [view, setView] = useState<View>({ x: 80, y: 80, zoom: 1 })
  const [issues, setIssues] = useState<ValidationIssue[]>(
    workflow?.version.validation.issues ?? [],
  )
  const viewportRef = useRef<HTMLDivElement>(null)
  const slug = current?.slug

  const change = (patch: Partial<WorkflowWrite>) => {
    setDraft((d) => ({ ...d, ...patch }))
    setDirty(true)
  }
  const updateGraph = (fn: (graph: WorkflowGraph) => WorkflowGraph) => {
    setDraft((d) => ({ ...d, graph: fn(d.graph) }))
    setDirty(true)
  }

  useLayoutEffect(() => {
    const el = viewportRef.current
    if (el)
      setView(fitView(draft.graph, types, el.clientWidth, el.clientHeight))
    // Fit once, when the editor opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Validate a short time after the last change.
  useEffect(() => {
    if (!slug) return
    const controller = new AbortController()
    const timer = setTimeout(() => {
      validateWorkflow(
        orgSlug,
        slug,
        { graph: draft.graph, settings: draft.settings },
        controller.signal,
      )
        .then((result) => setIssues(result.issues))
        .catch(() => undefined)
    }, 600)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [draft.graph, draft.settings, orgSlug, slug])

  const deleteSelection = () => {
    if (!selection || readOnly) return
    updateGraph((g) =>
      selection.kind === 'node'
        ? removeNode(g, selection.id)
        : removeEdge(g, selection.index),
    )
    setSelection(null)
  }

  const hasSelection = useRef(false)
  hasSelection.current = !!selection && !readOnly
  const keyHandler = useRef(deleteSelection)
  keyHandler.current = deleteSelection
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target
      if (
        target instanceof Element &&
        target.closest(
          'input, textarea, select, [contenteditable="true"], [role="dialog"], [role="listbox"]',
        )
      ) {
        return
      }
      if (e.key === 'Escape') setSelection(null)
      if (
        (e.key === 'Delete' || e.key === 'Backspace') &&
        hasSelection.current
      ) {
        e.preventDefault()
        keyHandler.current()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const stored = (saved: Workflow) => {
    setCurrent(saved)
    queryClient.setQueryData(queryKeys.workflow(orgSlug, saved.slug), saved)
    void queryClient.invalidateQueries({
      exact: true,
      queryKey: queryKeys.workflows(orgSlug),
    })
  }

  const save = useMutation({
    mutationFn: () =>
      slug
        ? updateWorkflow(orgSlug, slug, draft)
        : createWorkflow(orgSlug, draft),
    onError: (error) =>
      toast.error(
        `Failed to save the workflow: ${extractApiErrorDetail(error)}`,
      ),
    onSuccess: (saved) => {
      stored(saved)
      setDirty(false)
      setIssues(saved.version.validation.issues)
      if (!slug) {
        navigate(agentsPath('workflows', saved.slug), { replace: true })
      }
    },
  })

  const toggleActive = useMutation({
    mutationFn: (active: boolean) =>
      active ? activateWorkflow(orgSlug, slug!) : pauseWorkflow(orgSlug, slug!),
    onError: (error, active) => toast.error(activationError(error, active)),
    onSuccess: stored,
  })

  const onSave = () => {
    if (!draft.name.trim()) {
      toast.error('Give the workflow a name.')
      return
    }
    if (!draft.owner_team_slug) {
      setSelection(null)
      toast.error('Choose an owner team in the workflow settings.')
      return
    }
    save.mutate()
  }

  const onAdd = (
    type: StepType,
    position: Point,
    from?: { port: number; source: string },
  ) => {
    const node = createNode(draft.graph, type, position)
    updateGraph((g) => addNode(g, node, types, from))
    setSelection({ id: node.id, kind: 'node' })
  }

  const onPaletteAdd = (type: StepType) => {
    const el = viewportRef.current
    if (!el) return
    const center = toCanvas(
      { x: el.clientWidth / 2, y: el.clientHeight / 2 },
      { x: 0, y: 0 },
      view,
    )
    const selected =
      selection?.kind === 'node'
        ? (draft.graph.nodes.find((n) => n.id === selection.id) ?? null)
        : null
    const spot = placeNew(draft.graph, types, center, selected, type.trigger)
    onAdd(type, spot.position, spot.from)
  }

  const nodeIssues = (id: string) => issues.filter((i) => i.node_id === id)
  const summaries = useMemo(() => {
    const out: Record<string, NodeSummary> = {}
    for (const node of draft.graph.nodes) {
      const own = issues.filter((i) => i.node_id === node.id)
      const error = own.find((i) => i.severity === 'error')
      out[node.id] = error
        ? { text: error.message, tone: 'danger' }
        : own.length > 0
          ? { text: 'Needs configuration', tone: 'warning' }
          : {
              text:
                paramSummary(node.params) ||
                types[node.type]?.description ||
                '',
              tone: 'normal',
            }
    }
    return out
  }, [draft.graph.nodes, issues, types])
  const edgeErrors = useMemo(
    () =>
      new Set(
        issues.flatMap((i) => (i.edge_index === null ? [] : [i.edge_index])),
      ),
    [issues],
  )
  const needConfig = new Set(
    issues
      .filter((i) => i.severity === 'warning' && i.node_id)
      .map((i) => i.node_id),
  ).size

  const selectedNode =
    selection?.kind === 'node'
      ? draft.graph.nodes.find((n) => n.id === selection.id)
      : undefined
  const status = current?.status ?? 'draft'
  const savedLabel = dirty
    ? 'Unsaved changes'
    : current
      ? `Saved · v${current.latest_version}`
      : 'Not saved yet'

  return (
    <div
      className="flex flex-col"
      style={{ height: 'calc(100vh - 4rem - var(--assistant-height, 64px))' }}
    >
      <div className="border-tertiary flex h-14 shrink-0 items-center gap-2.5 border-b px-4">
        <Link
          className="text-secondary hover:bg-secondary hover:text-primary flex h-8 items-center gap-1.5 rounded-md px-2 text-sm"
          to={agentsPath('workflows')}
        >
          <ArrowLeft className="size-3.5" />
          Workflows
        </Link>
        <span className="text-tertiary">/</span>
        <input
          aria-label="Workflow name"
          className="hover:border-tertiary focus:border-amber-border h-8 w-55 rounded-md border border-transparent bg-transparent px-2 font-medium outline-none"
          disabled={readOnly}
          onChange={(e) => change({ name: e.target.value })}
          value={draft.name}
        />
        <StatusBadge status={status} />
        <span className="text-tertiary text-xs whitespace-nowrap">
          {savedLabel}
        </span>
        {needConfig > 0 && (
          <span className="text-amber-text flex items-center gap-1 text-xs whitespace-nowrap">
            <AlertTriangle className="size-3.25" />
            {needConfig === 1
              ? '1 step needs configuration'
              : `${needConfig} steps need configuration`}
          </span>
        )}
        <div className="flex-1" />
        {current && canWrite && (
          <label
            className="flex items-center gap-2 text-sm"
            title={dirty ? 'Save your changes before you activate.' : undefined}
          >
            <Switch
              checked={status === 'active'}
              disabled={dirty || toggleActive.isPending}
              onCheckedChange={(active) => toggleActive.mutate(active)}
            />
            {status === 'active' ? 'Active' : 'Inactive'}
          </label>
        )}
        {canWrite && (
          <Button
            disabled={save.isPending || (!!current && !dirty)}
            onClick={onSave}
            size="sm"
          >
            Save
          </Button>
        )}
      </div>

      <div className="flex min-h-0 flex-1">
        {paletteOpen && !readOnly && (
          <Palette
            onAdd={onPaletteAdd}
            onClose={() => setPaletteOpen(false)}
            types={stepTypes}
          />
        )}
        <div className="relative flex min-w-0 flex-1 flex-col">
          <Canvas
            edgeErrors={edgeErrors}
            graph={draft.graph}
            onAdd={onAdd}
            onConnect={(edge) => updateGraph((g) => connect(g, types, edge))}
            onMove={(id, position) =>
              updateGraph((g) => updateNode(g, id, { position }))
            }
            onOpenPalette={
              paletteOpen || readOnly ? null : () => setPaletteOpen(true)
            }
            onRemoveEdge={(index) => {
              updateGraph((g) => removeEdge(g, index))
              setSelection(null)
            }}
            onSelect={setSelection}
            onView={setView}
            readOnly={readOnly}
            selection={selection}
            summaries={summaries}
            types={types}
            view={view}
            viewportRef={viewportRef}
          />
          <div className="border-tertiary bg-primary flex h-10 shrink-0 items-center gap-2.5 border-t px-4">
            <span className="text-tertiary flex items-center gap-1.5 text-sm font-medium">
              <ChevronUp className="size-3.5" />
              Test run
            </span>
            <span className="text-tertiary truncate text-xs">
              Test runs arrive with the workflow engine.
            </span>
          </div>
        </div>
        <aside className="border-tertiary bg-primary flex w-80 shrink-0 flex-col border-l">
          {selectedNode ? (
            <NodePanel
              graph={draft.graph}
              issues={nodeIssues(selectedNode.id)}
              key={selectedNode.id}
              node={selectedNode}
              onChange={(patch) =>
                updateGraph((g) => updateNode(g, selectedNode.id, patch))
              }
              onDelete={deleteSelection}
              onDuplicate={() => {
                const copy = duplicateNode(draft.graph, selectedNode.id).node
                if (!copy) return
                updateGraph((g) => ({ ...g, nodes: [...g.nodes, copy] }))
                setSelection({ id: copy.id, kind: 'node' })
              }}
              onRemoveItem={(name, index) =>
                updateGraph((g) =>
                  name === 'branches' &&
                  types[selectedNode.type]?.ports === null
                    ? removeBranch(g, selectedNode.id, index)
                    : updateNode(g, selectedNode.id, {
                        params: {
                          ...selectedNode.params,
                          [name]: (
                            selectedNode.params[name] as unknown[]
                          ).filter((_, i) => i !== index),
                        },
                      }),
                )
              }
              orgSlug={orgSlug}
              readOnly={readOnly}
              types={types}
            />
          ) : selection?.kind === 'edge' ? (
            <EdgePanel
              graph={draft.graph}
              index={selection.index}
              onRemove={deleteSelection}
              readOnly={readOnly}
              types={types}
            />
          ) : (
            <SettingsPanel
              draft={draft}
              issues={issues.filter((i) => i.node_id === null)}
              onChange={change}
              orgSlug={orgSlug}
              readOnly={readOnly}
            />
          )}
        </aside>
      </div>
    </div>
  )
}

function activationError(error: unknown, active: boolean): string {
  if (error instanceof ApiError && error.status === 403) {
    const detail = (error.data as { detail?: { permissions?: string[] } })
      ?.detail
    if (detail?.permissions?.length) {
      return `You need ${detail.permissions.join(', ')} to activate this workflow.`
    }
  }
  if (error instanceof ApiError && error.status === 422 && active) {
    return 'Fix every issue before you activate the workflow.'
  }
  const verb = active ? 'activate' : 'pause'
  return `Failed to ${verb} the workflow: ${extractApiErrorDetail(error)}`
}
