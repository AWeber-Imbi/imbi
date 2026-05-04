import { useEffect, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  listProjectTypePlugins,
  listServicePlugins,
  listThirdPartyServices,
  replaceProjectTypePlugins,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
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
import type { PluginAssignmentCreate, PluginTab } from '@/types'

interface AssignmentDraft extends PluginAssignmentCreate {
  label: string
}

interface ProjectTypePluginsProps {
  orgSlug: string
  ptSlug: string
}

export function ProjectTypePlugins({
  orgSlug,
  ptSlug,
}: ProjectTypePluginsProps) {
  const queryClient = useQueryClient()
  const [showAdd, setShowAdd] = useState(false)
  const [selectedService, setSelectedService] = useState('')
  const [selectedPlugin, setSelectedPlugin] = useState('')
  const [selectedTab, setSelectedTab] = useState<PluginTab>('configuration')
  const [isDefault, setIsDefault] = useState(false)
  const [drafts, setDrafts] = useState<AssignmentDraft[]>([])
  const hasSeeded = useRef(false)

  const { data: existing } = useQuery({
    queryFn: ({ signal }) => listProjectTypePlugins(orgSlug, ptSlug, signal),
    queryKey: ['project-type-plugins', orgSlug, ptSlug],
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
    if (existing && !hasSeeded.current) {
      hasSeeded.current = true
      setDrafts(
        existing.map((a) => ({
          default: a.default,
          label: a.label,
          options: a.options,
          plugin_id: a.plugin_id,
          tab: a.tab,
        })),
      )
    }
  }, [existing])

  const saveMutation = useMutation({
    mutationFn: () =>
      replaceProjectTypePlugins(
        orgSlug,
        ptSlug,
        drafts.map((d) => ({
          default: d.default,
          options: d.options,
          plugin_id: d.plugin_id,
          tab: d.tab,
        })),
      ),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to save assignments')
    },
    onSuccess: () => {
      toast.success('Plugin assignments saved')
      hasSeeded.current = false
      void queryClient.invalidateQueries({
        queryKey: ['project-type-plugins', orgSlug, ptSlug],
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
        tab: selectedTab,
      },
    ])
    setShowAdd(false)
  }

  const handleRemove = (idx: number) => {
    setDrafts((prev) => prev.filter((_, i) => i !== idx))
  }

  const toggleDefault = (idx: number) => {
    setDrafts((prev) =>
      prev.map((d, i) => ({
        ...d,
        default: i === idx ? !d.default : d.default,
      })),
    )
  }

  const isDirty =
    JSON.stringify(drafts) !==
    JSON.stringify(
      (existing ?? []).map((a) => ({
        default: a.default,
        label: a.label,
        options: a.options,
        plugin_id: a.plugin_id,
        tab: a.tab,
      })),
    )

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between px-6 py-4">
          <CardTitle>Plugin Assignments</CardTitle>
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
              Add Plugin
            </Button>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          {drafts.length === 0 ? (
            <div className="py-8 text-center text-sm text-secondary">
              No plugins assigned. Add a plugin to enable Configuration or Logs
              tabs on projects of this type.
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Plugin</TableHead>
                  <TableHead>Tab</TableHead>
                  <TableHead>Default</TableHead>
                  <TableHead className="w-20" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {drafts.map((draft, idx) => (
                  <TableRow key={idx}>
                    <TableCell className="font-medium">{draft.label}</TableCell>
                    <TableCell>
                      <Badge variant="secondary">{draft.tab}</Badge>
                    </TableCell>
                    <TableCell>
                      <button
                        className={`text-sm ${draft.default ? 'text-info' : 'text-secondary hover:text-primary'}`}
                        onClick={() => toggleDefault(idx)}
                        type="button"
                      >
                        {draft.default ? '✓ Default' : 'Set as default'}
                      </button>
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
        </CardContent>
      </Card>

      <Dialog onOpenChange={setShowAdd} open={showAdd}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Plugin Assignment</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
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
                        <span className="ml-1 text-xs text-secondary">
                          ({p.plugin_slug})
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}
            <div className="flex items-center gap-2">
              <input
                checked={isDefault}
                id="is-default"
                onChange={(e) => setIsDefault(e.target.checked)}
                type="checkbox"
              />
              <Label htmlFor="is-default">Set as default for this tab</Label>
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <Button onClick={() => setShowAdd(false)} variant="outline">
                Cancel
              </Button>
              <Button disabled={!selectedPlugin} onClick={handleAdd}>
                Add
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
