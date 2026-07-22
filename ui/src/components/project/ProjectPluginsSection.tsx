import * as React from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'

import {
  getPluginPackage,
  listIntegrations,
  listProjectIntegrations,
  replaceProjectIntegrations,
} from '@/api/endpoints'
import {
  OverrideCountChevron,
  RemoveRowButton,
} from '@/components/plugin-options/ExpandableRowControls'
import { OptionRow } from '@/components/plugin-options/OptionRow'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Sk, Swap } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useExpandableRows } from '@/hooks/useExpandableRows'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type {
  Integration,
  PluginOption,
  PluginOptionDef,
  ProjectIntegrationAssignment,
} from '@/types'

interface OverrideOptionsEditorProps {
  draft: ProjectIntegrationAssignment
  idx: number
  onChange: (idx: number, name: string, next: unknown) => void
  pluginSlug: null | string
}

interface ProjectIntegrationRowProps {
  draft: ProjectIntegrationAssignment
  idx: number
  integrationName: string
  isExpanded: boolean
  onRemove: (idx: number) => void
  onToggle: (idx: number) => void
  onUpdateOption: (idx: number, name: string, next: unknown) => void
  pluginSlug: null | string
}

interface ProjectPluginsSectionProps {
  orgSlug: string
  projectId: string
}

export function ProjectPluginsSection({
  orgSlug,
  projectId,
}: ProjectPluginsSectionProps) {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [selectedIntegration, setSelectedIntegration] = useState('')
  const [selectedCapability, setSelectedCapability] = useState('')
  const [isDefault, setIsDefault] = useState(false)
  const [drafts, setDrafts] = useState<ProjectIntegrationAssignment[]>([])
  const lastSeedRef = useRef<null | string>(null)

  const { data: assignments, isLoading: assignmentsLoading } = useQuery({
    queryFn: ({ signal }) =>
      listProjectIntegrations(orgSlug, projectId, signal),
    queryKey: ['project-integrations', orgSlug, projectId],
    staleTime: 60 * 1000,
  })

  const { data: integrations } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listIntegrations(orgSlug, signal),
    queryKey: queryKeys.integrations(orgSlug),
    staleTime: 5 * 60 * 1000,
  })

  // Slug → Integration lookup for row labels and per-capability option
  // schemas (fetched via the integration's plugin).
  const integrationsBySlug = useMemo(() => {
    const map = new Map<string, Integration>()
    for (const i of integrations ?? []) map.set(i.slug, i)
    return map
  }, [integrations])

  useEffect(() => {
    if (!assignments) return
    // Only reseed drafts when the server snapshot actually changes;
    // otherwise a focus refetch or sibling invalidate would clobber
    // unsaved option edits.
    const hash = JSON.stringify(assignments)
    if (hash === lastSeedRef.current) return
    lastSeedRef.current = hash
    setDrafts(assignments)
  }, [assignments])

  const { expanded, removeRow, setExpanded, toggleExpanded } =
    useExpandableRows()

  const updateOption = (idx: number, name: string, next: unknown) => {
    setDrafts((prev) =>
      prev.map((d, i) => applyOptionEdit(d, i, idx, name, next)),
    )
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      replaceProjectIntegrations(orgSlug, projectId, { assignments: drafts }),
    onError: (err) => {
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to save integration overrides',
      )
    },
    onSuccess: () => {
      toast.success('Integration overrides saved')
      void queryClient.invalidateQueries({
        queryKey: ['project-integrations', orgSlug, projectId],
      })
    },
  })

  const selected = selectedIntegration
    ? integrationsBySlug.get(selectedIntegration)
    : undefined
  // Enabled capabilities are the only ones a project may override.
  const enabledCapabilities = selected
    ? Object.entries(selected.capabilities)
        .filter(([, toggle]) => toggle.enabled)
        .map(([kind]) => kind)
    : []

  const openAdd = () => {
    setSelectedIntegration('')
    setSelectedCapability('')
    setIsDefault(false)
    setShowAdd(true)
  }

  const handleAdd = () => {
    if (!selectedIntegration || !selectedCapability) return
    setDrafts((prev) => {
      const nextDrafts: ProjectIntegrationAssignment[] = [
        ...prev,
        {
          capability: selectedCapability,
          default: isDefault,
          env_payloads: {},
          identity_integration_slug: null,
          integration_slug: selectedIntegration,
          options: {},
        },
      ]
      // Auto-expand the freshly added row so the option editor is
      // visible without an extra click.
      setExpanded((p) => new Set(p).add(nextDrafts.length - 1))
      return nextDrafts
    })
    setShowAdd(false)
  }

  const handleRemove = (idx: number) => removeRow(idx, setDrafts)

  const isDirty = JSON.stringify(drafts) !== JSON.stringify(assignments ?? [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Integrations</CardTitle>
        <CardDescription className="text-secondary">
          Override an integration's capability options for this project.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-6 pt-0">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-secondary text-xs font-medium tracking-wider uppercase">
              Project overrides
            </p>
            <div className="flex gap-2">
              {isDirty && (
                <Button
                  disabled={saveMutation.isPending}
                  onClick={() => saveMutation.mutate()}
                  size="sm"
                >
                  {saveMutation.isPending ? 'Saving…' : 'Save Changes'}
                </Button>
              )}
              <Button onClick={openAdd} size="sm" variant="outline">
                <Plus className="mr-1 size-3" />
                Add Override
              </Button>
            </div>
          </div>

          <Swap
            ready={!assignmentsLoading}
            skeleton={<ProjectPluginsRowsSkeleton />}
          >
            {drafts.length === 0 ? (
              <p className="text-secondary text-sm">
                No project-level integration overrides.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Integration</TableHead>
                    <TableHead>Capability</TableHead>
                    <TableHead>Default</TableHead>
                    <TableHead className="w-16" />
                    <TableHead className="w-12" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {drafts.map((draft, idx) => (
                    <ProjectIntegrationRow
                      draft={draft}
                      idx={idx}
                      integrationName={
                        integrationsBySlug.get(draft.integration_slug)?.name ??
                        draft.integration_slug
                      }
                      isExpanded={expanded.has(idx)}
                      key={idx}
                      onRemove={handleRemove}
                      onToggle={toggleExpanded}
                      onUpdateOption={updateOption}
                      pluginSlug={
                        integrationsBySlug.get(draft.integration_slug)
                          ?.plugin ?? null
                      }
                    />
                  ))}
                </TableBody>
              </Table>
            )}
          </Swap>
        </div>
      </CardContent>

      <Dialog onOpenChange={setShowAdd} open={showAdd}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Integration Override</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 p-6">
            <div className="space-y-2">
              <Label>Integration</Label>
              <Select
                onValueChange={(v) => {
                  setSelectedIntegration(v)
                  setSelectedCapability('')
                }}
                value={selectedIntegration}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select integration…" />
                </SelectTrigger>
                <SelectContent>
                  {(integrations ?? []).map((i) => (
                    <SelectItem key={i.slug} value={i.slug}>
                      {i.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {selectedIntegration && (
              <div className="space-y-2">
                <Label>Capability</Label>
                <Select
                  onValueChange={setSelectedCapability}
                  value={selectedCapability}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select capability…" />
                  </SelectTrigger>
                  <SelectContent>
                    {enabledCapabilities.map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {kind}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex items-center gap-2">
              <Checkbox
                checked={isDefault}
                id="proj-is-default"
                onCheckedChange={(checked) => setIsDefault(checked === true)}
              />
              <Label htmlFor="proj-is-default">
                Set as default for this capability
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setShowAdd(false)} variant="outline">
              Cancel
            </Button>
            <Button disabled={!selectedCapability} onClick={handleAdd}>
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function adaptOption(opt: PluginOption): PluginOptionDef {
  return {
    choices: opt.choices ?? null,
    default: typeof opt.default === 'object' ? undefined : opt.default,
    description: opt.description ?? null,
    label: opt.label,
    name: opt.name,
    required: opt.required,
    type: opt.type,
  }
}

function applyOptionEdit(
  draft: ProjectIntegrationAssignment,
  i: number,
  idx: number,
  name: string,
  next: unknown,
): ProjectIntegrationAssignment {
  if (i !== idx) return draft
  const options = { ...draft.options }
  // Treat empty / null / undefined as "remove the override" so the
  // editor restores inherited / default behavior for that option.
  if (isClearValue(next)) delete options[name]
  else options[name] = next
  return { ...draft, options }
}

function isClearValue(v: unknown): boolean {
  return v === null || v === undefined || v === ''
}

// Fetches the integration's plugin manifest and renders the option editor
// for the selected capability's options. Falls back to a message when the
// plugin has no options for that capability.
function OverrideOptionsEditor({
  draft,
  idx,
  onChange,
  pluginSlug,
}: OverrideOptionsEditorProps) {
  const {
    data: pkg,
    error,
    isPending,
  } = useQuery({
    enabled: !!pluginSlug,
    queryFn: ({ signal }) => getPluginPackage(pluginSlug as string, signal),
    queryKey: queryKeys.pluginPackage(pluginSlug ?? ''),
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (!pluginSlug) {
    return (
      <div className="text-secondary px-6 py-4 text-sm">
        Integration is unavailable.
      </div>
    )
  }
  if (isPending) {
    return (
      <div className="text-secondary px-6 py-4 text-sm">Loading options…</div>
    )
  }
  if (error) {
    return (
      <div className="text-destructive px-6 py-4 text-sm">
        Couldn&apos;t load options for{' '}
        <span className="font-mono">{pluginSlug}</span>:{' '}
        {extractApiErrorDetail(error) ?? 'request failed'}.
      </div>
    )
  }
  const capability = pkg?.capabilities.find((c) => c.kind === draft.capability)
  const options = capability?.options ?? []
  if (options.length === 0) {
    return (
      <div className="text-secondary px-6 py-4 text-sm">
        This capability has no configurable options.
      </div>
    )
  }
  return (
    <div className="space-y-3 px-6 py-4">
      {options.map((opt) => {
        const overridden = opt.name in draft.options
        return (
          <OptionRow
            description={opt.description ?? null}
            key={opt.name}
            label={opt.label}
            name={`${draft.integration_slug}-${draft.capability}-${opt.name}`}
            onChange={(next) => onChange(idx, opt.name, next)}
            opt={adaptOption(opt)}
            value={overridden ? draft.options[opt.name] : ''}
          />
        )
      })}
    </div>
  )
}

// Single override row + its expanded option editor. Keyboard users can
// activate the expand toggle via Enter or Space.
function ProjectIntegrationRow({
  draft,
  idx,
  integrationName,
  isExpanded,
  onRemove,
  onToggle,
  onUpdateOption,
  pluginSlug,
}: ProjectIntegrationRowProps) {
  const overrideCount = Object.keys(draft.options).length
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onToggle(idx)
    }
  }
  return (
    <React.Fragment>
      <TableRow
        aria-expanded={isExpanded}
        className="hover:bg-secondary/40 focus-visible:ring-ring cursor-pointer focus-visible:ring-1 focus-visible:outline-none"
        onClick={() => onToggle(idx)}
        onKeyDown={handleKeyDown}
        role="button"
        tabIndex={0}
      >
        <TableCell className="font-medium">{integrationName}</TableCell>
        <TableCell>
          <Badge variant="secondary">{draft.capability}</Badge>
        </TableCell>
        <TableCell className="text-secondary text-sm">
          {draft.default ? 'Yes' : 'No'}
        </TableCell>
        <TableCell>
          <OverrideCountChevron count={overrideCount} isExpanded={isExpanded} />
        </TableCell>
        <TableCell>
          <RemoveRowButton
            ariaLabel="Remove override"
            onRemove={() => onRemove(idx)}
          />
        </TableCell>
      </TableRow>
      {isExpanded && (
        <TableRow className="bg-secondary/30 hover:bg-secondary/30">
          <TableCell className="p-0" colSpan={5}>
            <OverrideOptionsEditor
              draft={draft}
              idx={idx}
              onChange={onUpdateOption}
              pluginSlug={pluginSlug}
            />
          </TableCell>
        </TableRow>
      )}
    </React.Fragment>
  )
}

// Small footprint skeleton for the overrides region while the assignments
// load — a few rows echoing the name · capability-badge · default columns.
function ProjectPluginsRowsSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div aria-busy className="space-y-2">
      {Array.from({ length: rows }, (_, i) => (
        <div
          className="border-tertiary flex items-center gap-3 rounded border px-3 py-2"
          key={i}
        >
          <Sk line w={140} />
          <Sk h={18} r={4} w={84} />
          <div className="flex-1" />
          <Sk line w={28} />
        </div>
      ))}
    </div>
  )
}
