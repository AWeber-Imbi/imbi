import { useEffect, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createOperationsLogEntry,
  getProject,
  getProjects,
  type OperationsLogCreate,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Combobox } from '@/components/ui/combobox'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  OPERATIONS_LOG_ENTRY_TYPES,
  type OperationsLogEntryType,
} from '@/types'

export type NewOpsLogInitialValues = Partial<
  Pick<
    OperationsLogCreate,
    | 'description'
    | 'environment_slug'
    | 'link'
    | 'notes'
    | 'project_id'
    | 'ticket_slug'
    | 'version'
  >
> & { entry_type?: null | OperationsLogEntryType }

interface NewOpsLogDialogProps {
  initialValues?: NewOpsLogInitialValues
  isOpen: boolean
  onClose: () => void
  onEntryCreated?: (id: string) => void
}

export function NewOpsLogDialog({
  initialValues,
  isOpen,
  onClose,
  onEntryCreated,
}: NewOpsLogDialogProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()

  const [projectId, setProjectId] = useState('')
  const [environmentSlug, setEnvironmentSlug] = useState('')
  const [entryType, setEntryType] = useState<'' | OperationsLogEntryType>('')
  const [description, setDescription] = useState('')
  const [version, setVersion] = useState('')
  const [link, setLink] = useState('')
  const [ticketSlug, setTicketSlug] = useState('')
  const [notes, setNotes] = useState('')

  // Re-seed on every open so Duplicate reflects the source entry even if the
  // user previously opened, edited, and cancelled the dialog.
  useEffect(() => {
    if (!isOpen) return
    setProjectId(initialValues?.project_id ?? '')
    setEnvironmentSlug(initialValues?.environment_slug ?? '')
    setEntryType(initialValues?.entry_type ?? '')
    setDescription(initialValues?.description ?? '')
    setVersion(initialValues?.version ?? '')
    setLink(initialValues?.link ?? '')
    setTicketSlug(initialValues?.ticket_slug ?? '')
    setNotes(initialValues?.notes ?? '')
  }, [isOpen]) // eslint-disable-line react-hooks/exhaustive-deps

  const { data: projects = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  // Fetch the selected project on demand so we can show only its
  // environments. ``getProjects`` returns a lighter projection that
  // doesn't include environments.
  const { data: selectedProject, isLoading: selectedProjectLoading } = useQuery(
    {
      enabled: !!orgSlug && !!projectId && isOpen,
      queryFn: ({ signal }) => getProject(orgSlug, projectId, signal),
      queryKey: ['project', orgSlug, projectId],
    },
  )

  const projectOptions = useMemo(
    () =>
      [...projects].sort((a, b) => (a.name ?? '').localeCompare(b.name ?? '')),
    [projects],
  )

  const projectSlug = selectedProject?.slug ?? ''
  const projectEnvironments = selectedProject?.environments ?? []

  const createMutation = useMutation({
    mutationFn: (data: OperationsLogCreate) => createOperationsLogEntry(data),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['operations-log'] })
      queryClient.invalidateQueries({
        queryKey: ['projectActivity', orgSlug, projectId],
      })
      if (created?.id) onEntryCreated?.(created.id)
      handleClose()
    },
  })

  const canProceed =
    projectId && projectSlug && environmentSlug && entryType && description

  const handleSave = () => {
    if (!canProceed || createMutation.isPending) return
    createMutation.mutate({
      description,
      entry_type: entryType,
      environment_slug: environmentSlug,
      link: link || null,
      notes: notes || null,
      project_id: projectId,
      project_slug: projectSlug,
      ticket_slug: ticketSlug || null,
      version: version || null,
    })
  }

  const handleClose = () => {
    setProjectId('')
    setEnvironmentSlug('')
    setEntryType('')
    setDescription('')
    setVersion('')
    setLink('')
    setTicketSlug('')
    setNotes('')
    onClose()
  }

  return (
    <Dialog onOpenChange={(open) => !open && handleClose()} open={isOpen}>
      <DialogContent
        className="sm:max-w-2xl"
        style={{
          maxHeight: 'calc(100vh - var(--assistant-height, 0px) - 2rem - 10px)',
        }}
      >
        {/* Header */}
        <DialogHeader>
          <DialogTitle>New Ops Log Entry</DialogTitle>
        </DialogHeader>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-6">
            {/* Project */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-ops-project">
                Project <span className="text-red-500">*</span>
              </label>
              <Combobox
                onChange={(val) => {
                  setProjectId(val)
                  setEnvironmentSlug('')
                }}
                options={projectOptions.map((p) => ({
                  label: p.name ?? '',
                  value: p.id,
                }))}
                placeholder="Select project..."
                value={projectId}
              />
            </div>

            {/* Environment */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="new-ops-environment"
              >
                Environment <span className="text-red-500">*</span>
              </label>
              <Combobox
                disabled={
                  !projectId ||
                  selectedProjectLoading ||
                  projectEnvironments.length === 0
                }
                onChange={setEnvironmentSlug}
                options={projectEnvironments.map((env) => ({
                  label: env.name,
                  value: env.slug,
                }))}
                placeholder={
                  projectId
                    ? selectedProjectLoading
                      ? 'Loading environments...'
                      : projectEnvironments.length === 0
                        ? 'Project has no environments'
                        : 'Select environment...'
                    : 'Pick a project first'
                }
                value={environmentSlug}
              />
              <p className="text-sm text-muted-foreground">
                The environment the operation was performed in
              </p>
            </div>

            {/* Entry Type */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="new-ops-entry-type"
              >
                Entry Type <span className="text-red-500">*</span>
              </label>
              <Combobox
                onChange={(val) => setEntryType(val as OperationsLogEntryType)}
                options={OPERATIONS_LOG_ENTRY_TYPES.map((t) => ({
                  label: t,
                  value: t,
                }))}
                placeholder="Select type..."
                value={entryType}
              />
            </div>

            {/* Description */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="new-ops-description"
              >
                Description <span className="text-red-500">*</span>
              </label>
              <Textarea
                className="min-h-[96px] resize-none"
                id="new-ops-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Short summary of what was done"
                value={description}
              />
            </div>

            {/* Version */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-ops-version">
                Version
              </label>
              <Input
                id="new-ops-version"
                onChange={(e) => setVersion(e.target.value)}
                placeholder="e.g., 6.3.0"
                value={version}
              />
            </div>

            {/* Link */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-ops-link">
                Link
              </label>
              <Input
                id="new-ops-link"
                onChange={(e) => setLink(e.target.value)}
                placeholder="https://..."
                type="url"
                value={link}
              />
            </div>

            {/* Ticket */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-ops-ticket">
                Ticket
              </label>
              <Input
                id="new-ops-ticket"
                onChange={(e) => setTicketSlug(e.target.value)}
                placeholder="e.g., INC-1234"
                value={ticketSlug}
              />
            </div>

            {/* Notes */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-ops-notes">
                Notes
              </label>
              <Textarea
                className="min-h-[96px] resize-none"
                id="new-ops-notes"
                onChange={(e) => setNotes(e.target.value)}
                placeholder="Optional context for future readers"
                value={notes}
              />
            </div>
          </div>
        </div>

        {/* Error display */}
        {createMutation.error && (
          <div className="px-6 py-2">
            <Card className="border-destructive/50 bg-destructive/10 p-3">
              <p className="text-sm text-destructive">
                Failed to create entry: {String(createMutation.error)}
              </p>
            </Card>
          </div>
        )}

        {/* Footer */}
        <DialogFooter>
          <Button onClick={handleClose} variant="outline">
            Cancel
          </Button>
          <Button
            disabled={!canProceed || createMutation.isPending}
            onClick={handleSave}
          >
            {createMutation.isPending ? 'Saving...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
