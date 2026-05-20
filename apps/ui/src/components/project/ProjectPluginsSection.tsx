import * as React from 'react'
import { useEffect, useMemo, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { toast } from 'sonner'

import {
  getPluginManifest,
  listProjectPlugins,
  listServicePlugins,
  listThirdPartyServices,
  type PluginManifestResponse,
  replaceProjectPlugins,
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
import type {
  PluginAssignmentCreate,
  PluginAssignmentResponse,
  PluginTab,
} from '@/types'

interface OverrideDraft extends PluginAssignmentCreate {
  label: string
  // Always present on drafts (initialized to ``{}`` on add) so the
  // option editor can index it without a null guard.
  options: Record<string, unknown>
  plugin_slug: string
  source: PluginAssignmentResponse['source']
}

interface OverrideOptionsEditorProps {
  draft: OverrideDraft
  idx: number
  inheritedOptions: Record<string, unknown>
  onChange: (idx: number, name: string, next: unknown) => void
}

interface PluginOptionsListProps {
  draft: OverrideDraft
  idx: number
  inheritedOptions: Record<string, unknown>
  manifest: PluginManifestResponse
  onChange: (idx: number, name: string, next: unknown) => void
}

interface ProjectPluginOverrideRowProps {
  draft: OverrideDraft
  idx: number
  inheritedOptions: Record<string, unknown>
  isExpanded: boolean
  onRemove: (idx: number) => void
  onToggle: (idx: number) => void
  onUpdateOption: (idx: number, name: string, next: unknown) => void
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
  const [selectedService, setSelectedService] = useState('')
  const [selectedPlugin, setSelectedPlugin] = useState('')
  const [selectedTab, setSelectedTab] = useState<PluginTab>('configuration')
  const [isDefault, setIsDefault] = useState(false)
  const [drafts, setDrafts] = useState<OverrideDraft[]>([])
  const lastSeedRef = useRef<null | string>(null)

  const { data: merged } = useQuery({
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, projectId, signal),
    queryKey: ['project-plugins', orgSlug, projectId],
    staleTime: 60 * 1000,
  })

  const { data: services } = useQuery({
    queryFn: ({ signal }) => listThirdPartyServices(orgSlug, signal),
    queryKey: ['third-party-services', orgSlug],
    staleTime: 5 * 60 * 1000,
  })

  const { data: servicePlugins } = useQuery({
    enabled: !!selectedService,
    queryFn: ({ signal }) =>
      listServicePlugins(orgSlug, selectedService, signal),
    queryKey: ['service-plugins', orgSlug, selectedService],
    staleTime: 60 * 1000,
  })

  useEffect(() => {
    if (!merged) return
    const projectOnly = merged.filter((a) => a.source === 'project')
    const seed = projectOnly.map(assignmentToDraft)
    // Only reseed drafts when the server snapshot actually changes;
    // otherwise a focus refetch or sibling invalidate would clobber
    // unsaved option edits.
    const hash = JSON.stringify(seed)
    if (hash === lastSeedRef.current) return
    lastSeedRef.current = hash
    setDrafts(seed)
  }, [merged])

  // Inherited options keyed by ``plugin_id:tab`` -- shown as
  // placeholders inside the per-row option editor so users can see what
  // value they'd be overriding before picking one. Keying by tab too
  // means the same plugin on different tabs doesn't merge inherited
  // values.
  const inheritedOptionsByKey = useMemo(
    () => buildInheritedOptionsByKey(merged ?? []),
    [merged],
  )

  const { expanded, removeRow, setExpanded, toggleExpanded } =
    useExpandableRows()

  const updateOption = (idx: number, name: string, next: unknown) => {
    setDrafts((prev) =>
      prev.map((d, i) => applyOptionEdit(d, i, idx, name, next)),
    )
  }

  const saveMutation = useMutation({
    mutationFn: () =>
      replaceProjectPlugins(
        orgSlug,
        projectId,
        drafts.map((d) => ({
          default: d.default,
          options: d.options,
          plugin_id: d.plugin_id,
          tab: d.tab,
        })),
      ),
    onError: (err) => {
      toast.error(
        extractApiErrorDetail(err) ?? 'Failed to save plugin overrides',
      )
    },
    onSuccess: () => {
      toast.success('Plugin overrides saved')
      void queryClient.invalidateQueries({
        queryKey: ['project-plugins', orgSlug, projectId],
      })
    },
  })

  const openAdd = () => {
    setSelectedService('')
    setSelectedPlugin('')
    setSelectedTab('configuration')
    setIsDefault(false)
    setShowAdd(true)
  }

  const handleAdd = () => {
    const plugin = servicePlugins?.find((p) => p.id === selectedPlugin)
    if (!plugin) return
    setDrafts((prev) => {
      const nextDrafts = [
        ...prev,
        {
          default: isDefault,
          label: plugin.label,
          options: {} as Record<string, unknown>,
          plugin_id: plugin.id,
          plugin_slug: plugin.plugin_slug,
          source: 'project' as const,
          tab: selectedTab,
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

  const projectOnlyFromServer =
    merged?.filter((a) => a.source === 'project') ?? []
  const isDirty =
    JSON.stringify(drafts.map(draftToCompare)) !==
    JSON.stringify(projectOnlyFromServer.map(draftToCompare))

  const inherited = merged?.filter((a) => a.source === 'project_type') ?? []

  return (
    <Card>
      <CardHeader>
        <CardTitle>Plugins</CardTitle>
        <CardDescription className="text-secondary">
          Override or extend the plugin assignments inherited from the project
          type.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4 p-6 pt-0">
        {inherited.length > 0 && (
          <div>
            <p className="text-secondary mb-2 text-xs font-medium tracking-wider uppercase">
              Inherited from project type
            </p>
            <div className="flex flex-wrap gap-2">
              {inherited.map((a) => (
                <div
                  className="border-tertiary bg-secondary flex items-center gap-1.5 rounded border px-2 py-1 text-xs"
                  key={`${a.plugin_id}:${a.tab}`}
                >
                  <span className="text-primary">{a.label}</span>
                  <Badge variant="secondary">{a.tab}</Badge>
                  {a.default && <span className="text-tertiary">default</span>}
                </div>
              ))}
            </div>
          </div>
        )}

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

          {drafts.length === 0 ? (
            <p className="text-secondary text-sm">
              No project-level overrides. Using project type defaults.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Plugin</TableHead>
                  <TableHead>Tab</TableHead>
                  <TableHead>Default</TableHead>
                  <TableHead className="w-16" />
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {drafts.map((draft, idx) => (
                  <ProjectPluginOverrideRow
                    draft={draft}
                    idx={idx}
                    inheritedOptions={
                      inheritedOptionsByKey[
                        inheritedKey(draft.plugin_id, draft.tab)
                      ] ?? {}
                    }
                    isExpanded={expanded.has(idx)}
                    key={idx}
                    onRemove={handleRemove}
                    onToggle={toggleExpanded}
                    onUpdateOption={updateOption}
                  />
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </CardContent>

      <Dialog onOpenChange={setShowAdd} open={showAdd}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Plugin Override</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 p-6">
            <div className="space-y-2">
              <Label>Tab</Label>
              <Select
                onValueChange={(v) => setSelectedTab(v as PluginTab)}
                value={selectedTab}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="configuration">Configuration</SelectItem>
                  <SelectItem value="logs">Logs</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label>Service</Label>
              <Select
                onValueChange={(v) => {
                  setSelectedService(v)
                  setSelectedPlugin('')
                }}
                value={selectedService}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select service…" />
                </SelectTrigger>
                <SelectContent>
                  {(services ?? []).map((svc) => (
                    <SelectItem key={svc.slug} value={svc.slug}>
                      {svc.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            {selectedService && (
              <div className="space-y-2">
                <Label>Plugin</Label>
                <Select
                  onValueChange={setSelectedPlugin}
                  value={selectedPlugin}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select plugin…" />
                  </SelectTrigger>
                  <SelectContent>
                    {(servicePlugins ?? []).map((p) => (
                      <SelectItem key={p.id} value={p.id}>
                        {p.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex items-center gap-2">
              <input
                checked={isDefault}
                id="proj-is-default"
                onChange={(e) => setIsDefault(e.target.checked)}
                type="checkbox"
              />
              <Label htmlFor="proj-is-default">
                Set as default for this tab
              </Label>
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setShowAdd(false)} variant="outline">
              Cancel
            </Button>
            <Button disabled={!selectedPlugin} onClick={handleAdd}>
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  )
}

function applyOptionEdit(
  draft: OverrideDraft,
  i: number,
  idx: number,
  name: string,
  next: unknown,
): OverrideDraft {
  if (i !== idx) return draft
  const options = { ...draft.options }
  // Treat empty / null / undefined as "remove the override" so the
  // editor restores inherited / default behavior for that option.
  if (isClearValue(next)) delete options[name]
  else options[name] = next
  return { ...draft, options }
}

function assignmentToDraft(a: PluginAssignmentResponse): OverrideDraft {
  return {
    default: a.default,
    label: a.label,
    options: a.options ?? {},
    plugin_id: a.plugin_id,
    plugin_slug: a.plugin_slug,
    source: a.source,
    tab: a.tab,
  }
}

function buildInheritedOptionsByKey(merged: PluginAssignmentResponse[]) {
  const out: Record<string, Record<string, unknown>> = {}
  for (const a of merged) {
    if (a.source !== 'project_type') continue
    out[inheritedKey(a.plugin_id, a.tab)] = a.options ?? {}
  }
  return out
}

function draftToCompare(d: {
  default: boolean
  label: string
  options: Record<string, unknown>
  plugin_id: string
  tab: PluginTab
}) {
  return {
    default: d.default,
    label: d.label,
    options: d.options,
    plugin_id: d.plugin_id,
    tab: d.tab,
  }
}

function hasRenderableManifest(
  isPending: boolean,
  error: unknown,
  manifest: PluginManifestResponse | undefined,
): manifest is PluginManifestResponse {
  if (isPending) return false
  if (error) return false
  if (!manifest) return false
  return manifest.options.length > 0
}

// Composite key so the same plugin can be assigned on different tabs
// (e.g. ``configuration`` and ``logs``) without one overwriting the
// other in the inherited-options lookup.
function inheritedKey(pluginId: string, tab: PluginTab) {
  return `${pluginId}:${tab}`
}

// Placeholder text shown when the override is empty: prefer the
// project-type-inherited value, fall back to the manifest default, and
// finally to ``Inherits default`` when nothing concrete is available.
function inheritedPlaceholder(
  opt: import('@/types').PluginOptionDef,
  inheritedRaw: unknown,
): string {
  const value = pickInheritedValue(inheritedRaw, opt.default ?? null)
  return value === null ? 'Inherits default' : `Inherits: ${String(value)}`
}

function isClearValue(v: unknown): boolean {
  return v === null || v === undefined || v === ''
}

function ManifestStateMessage({
  error,
  isPending,
  pluginSlug,
}: {
  error: Error | null
  isPending: boolean
  pluginSlug: string
}) {
  if (isPending)
    return (
      <div className="text-secondary px-6 py-4 text-sm">Loading options…</div>
    )
  if (error)
    return (
      <div className="text-destructive px-6 py-4 text-sm">
        Couldn&apos;t load options for{' '}
        <span className="font-mono">{pluginSlug}</span>:{' '}
        {extractApiErrorDetail(error) ?? 'request failed'}.
      </div>
    )
  return (
    <div className="text-secondary px-6 py-4 text-sm">
      This plugin has no configurable options.
    </div>
  )
}

function OverrideOptionsEditor({
  draft,
  idx,
  inheritedOptions,
  onChange,
}: OverrideOptionsEditorProps) {
  const {
    data: manifest,
    error: manifestError,
    isPending,
  } = useQuery({
    queryFn: ({ signal }) => getPluginManifest(draft.plugin_slug, signal),
    queryKey: ['plugin-manifest', draft.plugin_slug],
    retry: false,
    staleTime: 5 * 60 * 1000,
  })

  if (!hasRenderableManifest(isPending, manifestError, manifest))
    return (
      <ManifestStateMessage
        error={manifestError ?? null}
        isPending={isPending}
        pluginSlug={draft.plugin_slug}
      />
    )
  return (
    <PluginOptionsList
      draft={draft}
      idx={idx}
      inheritedOptions={inheritedOptions}
      manifest={manifest}
      onChange={onChange}
    />
  )
}

function pickInheritedValue(inheritedRaw: unknown, fallback: unknown): unknown {
  if (inheritedRaw === undefined) return fallback
  if (inheritedRaw === null) return fallback
  return inheritedRaw
}

function PluginOptionsList({
  draft,
  idx,
  inheritedOptions,
  manifest,
  onChange,
}: PluginOptionsListProps) {
  return (
    <div className="space-y-3 px-6 py-4">
      {manifest.options.map((opt) => {
        const overridden = opt.name in draft.options
        return (
          <OptionRow
            description={opt.description ?? null}
            key={opt.name}
            label={opt.label}
            name={`${draft.plugin_id}-${opt.name}`}
            onChange={(next) => onChange(idx, opt.name, next)}
            opt={opt}
            placeholder={
              overridden
                ? undefined
                : inheritedPlaceholder(opt, inheritedOptions[opt.name])
            }
            value={overridden ? draft.options[opt.name] : ''}
          />
        )
      })}
    </div>
  )
}

// Single override row + its expanded option editor pulled out of the
// parent's drafts.map so the parent stays under the complexity gate
// and so keyboard users can activate the expand toggle via Enter or
// Space (the bare clickable row was mouse-only).
function ProjectPluginOverrideRow({
  draft,
  idx,
  inheritedOptions,
  isExpanded,
  onRemove,
  onToggle,
  onUpdateOption,
}: ProjectPluginOverrideRowProps) {
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
        <TableCell className="font-medium">{draft.label}</TableCell>
        <TableCell>
          <Badge variant="secondary">{draft.tab}</Badge>
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
              inheritedOptions={inheritedOptions}
              onChange={onUpdateOption}
            />
          </TableCell>
        </TableRow>
      )}
    </React.Fragment>
  )
}
