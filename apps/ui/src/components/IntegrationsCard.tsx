import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Plus, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  createProjectService,
  deleteProjectService,
  listProjectServices,
  listThirdPartyServices,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
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

interface IntegrationsCardProps {
  orgSlug: string
  projectId: string
}

const EMPTY_FORM = {
  canonicalUrl: '',
  dashboardUrl: '',
  identifier: '',
  serviceSlug: '',
}

export function IntegrationsCard({
  orgSlug,
  projectId,
}: IntegrationsCardProps) {
  const queryClient = useQueryClient()
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)
  const [deleteTarget, setDeleteTarget] = useState<null | string>(null)

  const { data: services = [] } = useQuery({
    enabled: !!orgSlug && !!projectId,
    queryFn: ({ signal }) => listProjectServices(orgSlug, projectId, signal),
    queryKey: ['projectServices', orgSlug, projectId],
  })

  const { data: thirdPartyServices = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listThirdPartyServices(orgSlug, signal),
    queryKey: ['thirdPartyServices', orgSlug],
  })

  const invalidate = () => {
    queryClient.invalidateQueries({
      queryKey: ['projectServices', orgSlug, projectId],
    })
    // The dashboard URL is mirrored into the project's links, so refresh
    // the project view too.
    queryClient.invalidateQueries({
      queryKey: ['project', orgSlug, projectId],
    })
  }

  // Services the project does not already exist in — can't connect the
  // same service twice.
  const connectableServices = useMemo(() => {
    const connected = new Set(services.map((s) => s.third_party_service_slug))
    return thirdPartyServices.filter((s) => !connected.has(s.slug))
  }, [services, thirdPartyServices])

  const createMutation = useMutation({
    mutationFn: () =>
      createProjectService(orgSlug, projectId, {
        canonical_url: form.canonicalUrl.trim() || null,
        dashboard_url: form.dashboardUrl.trim() || null,
        identifier: form.identifier.trim(),
        third_party_service_slug: form.serviceSlug,
      }),
    onError: (error) => {
      toast.error(`Failed to add integration: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      toast.success('Integration added')
      setAddOpen(false)
      setForm(EMPTY_FORM)
      invalidate()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (serviceSlug: string) =>
      deleteProjectService(orgSlug, projectId, serviceSlug),
    onError: (error) => {
      toast.error(
        `Failed to remove integration: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      toast.success('Integration removed')
      invalidate()
    },
  })

  const canSubmit =
    !!form.serviceSlug && !!form.identifier.trim() && !createMutation.isPending

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between">
        <div className="space-y-1.5">
          <CardTitle>Integrations</CardTitle>
          <CardDescription>
            Third-party services this project exists in, with the stable
            identifier and the canonical API and dashboard URLs.
          </CardDescription>
        </div>
        <Button
          disabled={connectableServices.length === 0}
          onClick={() => {
            setForm(EMPTY_FORM)
            setAddOpen(true)
          }}
          size="sm"
          variant="outline"
        >
          <Plus className="size-4" />
          Add
        </Button>
      </CardHeader>
      <CardContent>
        {services.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            This project is not connected to any third-party services.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Service</TableHead>
                <TableHead>Identifier</TableHead>
                <TableHead>API URL</TableHead>
                <TableHead>Dashboard URL</TableHead>
                <TableHead className="w-12" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {services.map((svc) => (
                <TableRow key={svc.third_party_service_slug}>
                  <TableCell>{svc.third_party_service_name}</TableCell>
                  <TableCell className="font-mono text-sm">
                    {svc.identifier}
                  </TableCell>
                  <TableCell>
                    <UrlCell url={svc.canonical_url} />
                  </TableCell>
                  <TableCell>
                    <UrlCell url={svc.dashboard_url} />
                  </TableCell>
                  <TableCell>
                    <Button
                      aria-label={`Remove ${svc.third_party_service_name} integration`}
                      onClick={() =>
                        setDeleteTarget(svc.third_party_service_slug)
                      }
                      size="sm"
                      variant="ghost"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <Dialog onOpenChange={setAddOpen} open={addOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add Integration</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 p-6">
            <div className="space-y-2">
              <Label htmlFor="integration-service">Service</Label>
              <Select
                onValueChange={(value) =>
                  setForm((f) => ({ ...f, serviceSlug: value }))
                }
                value={form.serviceSlug}
              >
                <SelectTrigger id="integration-service">
                  <SelectValue placeholder="Select a service…" />
                </SelectTrigger>
                <SelectContent>
                  {connectableServices.map((svc) => (
                    <SelectItem key={svc.slug} value={svc.slug}>
                      {svc.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="integration-identifier">Identifier</Label>
              <Input
                id="integration-identifier"
                onChange={(e) =>
                  setForm((f) => ({ ...f, identifier: e.target.value }))
                }
                placeholder="e.g. 134741 or conv:account"
                value={form.identifier}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="integration-canonical">API URL</Label>
              <Input
                id="integration-canonical"
                onChange={(e) =>
                  setForm((f) => ({ ...f, canonicalUrl: e.target.value }))
                }
                placeholder="Canonical API URL (returns JSON)"
                value={form.canonicalUrl}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="integration-dashboard">Dashboard URL</Label>
              <Input
                id="integration-dashboard"
                onChange={(e) =>
                  setForm((f) => ({ ...f, dashboardUrl: e.target.value }))
                }
                placeholder="Human dashboard URL (optional)"
                value={form.dashboardUrl}
              />
            </div>
          </div>
          <DialogFooter>
            <Button onClick={() => setAddOpen(false)} variant="outline">
              Cancel
            </Button>
            <Button
              disabled={!canSubmit}
              onClick={() => createMutation.mutate()}
            >
              Add
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        confirmLabel="Remove"
        description={
          deleteTarget
            ? `This disconnects the ${deleteTarget} integration and removes its dashboard link.`
            : ''
        }
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget)
          setDeleteTarget(null)
        }}
        open={!!deleteTarget}
        title="Remove integration?"
      />
    </Card>
  )
}

function UrlCell({ url }: { url?: null | string }) {
  if (!url) {
    return <span className="text-muted-foreground">—</span>
  }
  return (
    <a
      className="text-primary inline-flex items-center gap-1 hover:underline"
      href={url}
      rel="noopener noreferrer"
      target="_blank"
    >
      <span className="max-w-[18rem] truncate">{url}</span>
      <ExternalLink className="size-3 shrink-0" />
    </a>
  )
}
