import { useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createOperationsLogEntry,
  getProject,
  getProjects,
  type OperationsLogCreate,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  OPERATIONS_LOG_ENTRY_TYPES,
  type OperationsLogEntryType,
} from '@/types'

interface NewOpsLogDialogProps {
  isOpen: boolean
  onClose: () => void
  onEntryCreated?: (id: string) => void
}

export function NewOpsLogDialog({
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

  if (!isOpen) return null

  return (
    <div
      aria-label="New Ops Log Entry"
      aria-modal="true"
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-center"
      onKeyDown={(e) => {
        if (e.key === 'Escape') handleClose()
      }}
      role="dialog"
      style={{
        bottom: 'var(--assistant-height, 0px)',
      }}
    >
      <button
        aria-label="Close dialog"
        className="absolute inset-0 bg-black/50"
        onClick={handleClose}
        type="button"
      />
      <div
        className="relative mx-4 flex w-full max-w-2xl flex-col rounded-lg bg-white shadow-xl"
        style={{
          maxHeight: 'calc(100vh - var(--assistant-height, 0px) - 2rem - 10px)',
        }}
      >
        {/* Header */}
        <div className="border-b p-6">
          <h2 className="text-lg font-semibold text-slate-900">
            New Ops Log Entry
          </h2>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-6">
            {/* Project */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-project"
              >
                Project <span className="text-red-500">*</span>
              </label>
              <select
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
                id="new-ops-project"
                onChange={(e) => {
                  setProjectId(e.target.value)
                  setEnvironmentSlug('')
                }}
                value={projectId}
              >
                <option value="">Select project...</option>
                {projectOptions.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Environment */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-environment"
              >
                Environment <span className="text-red-500">*</span>
              </label>
              <select
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm disabled:bg-slate-50 disabled:text-slate-400"
                disabled={
                  !projectId ||
                  selectedProjectLoading ||
                  projectEnvironments.length === 0
                }
                id="new-ops-environment"
                onChange={(e) => setEnvironmentSlug(e.target.value)}
                value={environmentSlug}
              >
                <option value="">
                  {projectId
                    ? selectedProjectLoading
                      ? 'Loading environments...'
                      : projectEnvironments.length === 0
                        ? 'Project has no environments'
                        : 'Select environment...'
                    : 'Pick a project first'}
                </option>
                {projectEnvironments.map((env) => (
                  <option key={env.slug} value={env.slug}>
                    {env.name}
                  </option>
                ))}
              </select>
              <p className="text-sm text-slate-500">
                The environment the operation was performed in
              </p>
            </div>

            {/* Entry Type */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-entry-type"
              >
                Entry Type <span className="text-red-500">*</span>
              </label>
              <select
                className="w-full rounded-md border border-slate-200 px-3 py-2 text-sm"
                id="new-ops-entry-type"
                onChange={(e) =>
                  setEntryType(e.target.value as OperationsLogEntryType)
                }
                value={entryType}
              >
                <option value="">Select type...</option>
                {OPERATIONS_LOG_ENTRY_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </div>

            {/* Description */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-description"
              >
                Description <span className="text-red-500">*</span>
              </label>
              <textarea
                className="min-h-[96px] w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-sm"
                id="new-ops-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Short summary of what was done"
                value={description}
              />
            </div>

            {/* Version */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-version"
              >
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
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-link"
              >
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
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-ticket"
              >
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
              <label
                className="text-sm font-medium text-slate-900"
                htmlFor="new-ops-notes"
              >
                Notes
              </label>
              <textarea
                className="min-h-[96px] w-full resize-none rounded-md border border-slate-200 px-3 py-2 text-sm"
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
            <Card className="border-red-200 bg-red-50 p-3">
              <p className="text-sm text-red-700">
                Failed to create entry: {String(createMutation.error)}
              </p>
            </Card>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 border-t p-6">
          <Button onClick={handleClose} variant="outline">
            Cancel
          </Button>
          <Button
            disabled={!canProceed || createMutation.isPending}
            onClick={handleSave}
          >
            {createMutation.isPending ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>
    </div>
  )
}
