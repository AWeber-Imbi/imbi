import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  createProject,
  listEnvironments,
  listProjectTypes,
  listTeams,
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
import { slugify } from '@/lib/utils'
import type { ProjectCreate } from '@/types'

interface NewProjectDialogProps {
  isOpen: boolean
  onClose: () => void
  onProjectCreated?: (id: string) => void
}

export function NewProjectDialog({
  isOpen,
  onClose,
  onProjectCreated,
}: NewProjectDialogProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()

  // Basic fields
  const [teamSlug, setTeamSlug] = useState('')
  const [projectTypeSlug, setProjectTypeSlug] = useState('')
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [selectedEnvSlugs, setSelectedEnvSlugs] = useState<string[]>([])

  const { data: teams = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: ['teams', orgSlug],
  })

  const { data: projectTypes = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    queryKey: ['projectTypes', orgSlug],
  })

  const { data: environments = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
  })

  const createMutation = useMutation({
    mutationFn: (data: ProjectCreate) => createProject(orgSlug, data),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: ['projects', orgSlug] })
      onProjectCreated?.(created.id)
      handleClose()
    },
  })

  const handleNameChange = (value: string) => {
    setName(value)
    if (!slug || slug === slugify(name)) {
      setSlug(slugify(value))
    }
  }

  const toggleEnv = (envSlug: string) => {
    setSelectedEnvSlugs((prev) =>
      prev.includes(envSlug)
        ? prev.filter((s) => s !== envSlug)
        : [...prev, envSlug],
    )
  }

  const handleSave = () => {
    if (!orgSlug || !canProceed || createMutation.isPending) return
    const projectData: ProjectCreate = {
      description: description || null,
      environment_slugs:
        selectedEnvSlugs.length > 0 ? selectedEnvSlugs : undefined,
      name,
      project_type_slugs: [projectTypeSlug],
      slug,
      team_slug: teamSlug,
    }
    createMutation.mutate(projectData)
  }

  const handleClose = () => {
    setTeamSlug('')
    setProjectTypeSlug('')
    setName('')
    setSlug('')
    setDescription('')
    setSelectedEnvSlugs([])
    onClose()
  }

  const canProceed = teamSlug && projectTypeSlug && name && slug

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
          <DialogTitle>Create New Project</DialogTitle>
        </DialogHeader>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="space-y-6">
            {/* Team */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-project-team">
                Team <span className="text-red-500">*</span>
              </label>
              <Combobox
                onChange={setTeamSlug}
                options={teams.map((t) => ({
                  label: t.name,
                  value: t.slug,
                }))}
                placeholder="Select team..."
                value={teamSlug}
              />
              <p className="text-muted-foreground text-sm">
                Team that owns this project
              </p>
            </div>

            {/* Project Type */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-project-type">
                Project Type <span className="text-red-500">*</span>
              </label>
              <Combobox
                onChange={setProjectTypeSlug}
                options={projectTypes.map((pt) => ({
                  label: pt.name,
                  value: pt.slug,
                }))}
                placeholder="Select project type..."
                value={projectTypeSlug}
              />
              <p className="text-muted-foreground text-sm">
                Type of the new project
              </p>
            </div>

            {/* Name */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-project-name">
                Name <span className="text-red-500">*</span>
              </label>
              <Input
                id="new-project-name"
                onChange={(e) => handleNameChange(e.target.value)}
                placeholder="e.g., My Service"
                value={name}
              />
              <p className="text-muted-foreground text-sm">
                Human-readable name for this project
              </p>
            </div>

            {/* Slug */}
            <div className="space-y-2">
              <label className="text-sm font-medium" htmlFor="new-project-slug">
                Slug <span className="text-red-500">*</span>
              </label>
              <Input
                id="new-project-slug"
                onChange={(e) => setSlug(e.target.value)}
                placeholder="e.g., my-service"
                value={slug}
              />
              <p className="text-muted-foreground text-sm">
                URL-friendly identifier for this project
              </p>
            </div>

            {/* Description */}
            <div className="space-y-2">
              <label
                className="text-sm font-medium"
                htmlFor="new-project-description"
              >
                Description
              </label>
              <Textarea
                className="min-h-30 resize-none"
                id="new-project-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Provide a high-level purpose and context for the project"
                value={description}
              />
            </div>

            {/* Environments */}
            {environments.length > 0 && (
              <div className="space-y-2">
                <label className="text-sm font-medium">Environments</label>
                <div className="flex flex-wrap gap-2">
                  {environments.map((env) => (
                    <button
                      className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                        selectedEnvSlugs.includes(env.slug)
                          ? 'border-amber-border bg-amber-border/10 text-amber-text'
                          : 'border-input bg-background text-muted-foreground hover:border-foreground/30'
                      }`}
                      key={env.slug}
                      onClick={() => toggleEnv(env.slug)}
                      type="button"
                    >
                      {env.name}
                    </button>
                  ))}
                </div>
                <p className="text-muted-foreground text-sm">
                  The environment the project runs in
                </p>
              </div>
            )}
          </div>
        </div>

        {/* Error display */}
        {createMutation.error && (
          <div className="px-6 py-2">
            <Card className="border-destructive/50 bg-destructive/10 p-3">
              <p className="text-destructive text-sm">
                Failed to create project: {String(createMutation.error)}
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
            {createMutation.isPending ? 'Creating...' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
