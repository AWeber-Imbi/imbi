import { useEffect, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  listProjectPlugins,
  listServicePlugins,
  listThirdPartyServices,
  replaceProjectPlugins,
} from '@/api/endpoints'
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
import { extractApiErrorDetail } from '@/lib/apiError'
import type {
  PluginAssignmentCreate,
  PluginAssignmentResponse,
  PluginTab,
} from '@/types'

interface OverrideDraft extends PluginAssignmentCreate {
  label: string
  source: PluginAssignmentResponse['source']
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
    if (merged) {
      const projectOnly = merged.filter((a) => a.source === 'project')
      setDrafts(
        projectOnly.map((a) => ({
          default: a.default,
          label: a.label,
          options: a.options,
          plugin_id: a.plugin_id,
          source: a.source,
          tab: a.tab,
        })),
      )
    }
  }, [merged])

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
    setDrafts((prev) => [
      ...prev,
      {
        default: isDefault,
        label: plugin.label,
        options: {},
        plugin_id: plugin.id,
        source: 'project',
        tab: selectedTab,
      },
    ])
    setShowAdd(false)
  }

  const handleRemove = (idx: number) => {
    setDrafts((prev) => prev.filter((_, i) => i !== idx))
  }

  const projectOnlyFromServer =
    merged?.filter((a) => a.source === 'project') ?? []
  const isDirty =
    JSON.stringify(
      drafts.map(({ default: d, label, options, plugin_id, tab }) => ({
        default: d,
        label,
        options,
        plugin_id,
        tab,
      })),
    ) !==
    JSON.stringify(
      projectOnlyFromServer.map(
        ({ default: d, label, options, plugin_id, tab }) => ({
          default: d,
          label,
          options,
          plugin_id,
          tab,
        }),
      ),
    )

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
            <p className="mb-2 text-xs font-medium uppercase tracking-wider text-secondary">
              Inherited from project type
            </p>
            <div className="flex flex-wrap gap-2">
              {inherited.map((a) => (
                <div
                  className="flex items-center gap-1.5 rounded border border-tertiary bg-secondary px-2 py-1 text-xs"
                  key={a.plugin_id}
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
            <p className="text-xs font-medium uppercase tracking-wider text-secondary">
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
                <Plus className="mr-1 h-3 w-3" />
                Add Override
              </Button>
            </div>
          </div>

          {drafts.length === 0 ? (
            <p className="text-sm text-secondary">
              No project-level overrides. Using project type defaults.
            </p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Plugin</TableHead>
                  <TableHead>Tab</TableHead>
                  <TableHead>Default</TableHead>
                  <TableHead className="w-12" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {drafts.map((draft, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium">{draft.label}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{draft.tab}</Badge>
                    </TableCell>
                    <TableCell className="text-sm text-secondary">
                      {draft.default ? 'Yes' : 'No'}
                    </TableCell>
                    <TableCell>
                      <Button
                        onClick={() => handleRemove(idx)}
                        size="icon"
                        variant="ghost"
                      >
                        <Trash2 className="h-3 w-3 text-destructive" />
                      </Button>
                    </TableCell>
                  </TableRow>
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
