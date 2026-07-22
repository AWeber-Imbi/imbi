import { useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'

import { createProject } from '@/api/endpoints'
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
import { Label } from '@/components/ui/label'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import { Sk, Swap } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  useEnvironments,
  useProjectTypes,
  useTeams,
} from '@/hooks/useOrgResources'
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

  const { data: teams = [], isLoading: teamsLoading } = useTeams(orgSlug, {
    enabled: isOpen,
  })
  const { data: projectTypes = [], isLoading: projectTypesLoading } =
    useProjectTypes(orgSlug, {
      enabled: isOpen,
    })
  const { data: environments = [], isLoading: environmentsLoading } =
    useEnvironments(orgSlug, {
      enabled: isOpen,
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
      description: description.trim() || null,
      environment_slugs:
        selectedEnvSlugs.length > 0 ? selectedEnvSlugs : undefined,
      name: name.trim(),
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
              <Label className="text-sm font-medium" htmlFor="new-project-team">
                Team <RequiredAsterisk />
              </Label>
              <Swap ready={!teamsLoading} skeleton={<FieldSkeleton />}>
                <Combobox
                  onChange={setTeamSlug}
                  options={teams.map((t) => ({
                    label: t.name,
                    value: t.slug,
                  }))}
                  placeholder="Select team..."
                  value={teamSlug}
                />
              </Swap>
              <p className="text-muted-foreground text-sm">
                Team that owns this project
              </p>
            </div>

            {/* Project Type */}
            <div className="space-y-2">
              <Label className="text-sm font-medium" htmlFor="new-project-type">
                Project Type <RequiredAsterisk />
              </Label>
              <Swap ready={!projectTypesLoading} skeleton={<FieldSkeleton />}>
                <Combobox
                  onChange={setProjectTypeSlug}
                  options={projectTypes.map((pt) => ({
                    label: pt.name,
                    value: pt.slug,
                  }))}
                  placeholder="Select project type..."
                  value={projectTypeSlug}
                />
              </Swap>
              <p className="text-muted-foreground text-sm">
                Type of the new project
              </p>
            </div>

            {/* Name */}
            <div className="space-y-2">
              <Label className="text-sm font-medium" htmlFor="new-project-name">
                Name <RequiredAsterisk />
              </Label>
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
              <Label className="text-sm font-medium" htmlFor="new-project-slug">
                Slug <RequiredAsterisk />
              </Label>
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
              <Label
                className="text-sm font-medium"
                htmlFor="new-project-description"
              >
                Description
              </Label>
              <Textarea
                className="min-h-30 resize-none"
                id="new-project-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Provide a high-level purpose and context for the project"
                value={description}
              />
            </div>

            {/* Environments */}
            {environmentsLoading && (
              <div className="space-y-2">
                <Label className="text-sm font-medium">Environments</Label>
                <ChipsSkeleton />
              </div>
            )}
            {!environmentsLoading && environments.length > 0 && (
              <div className="space-y-2">
                <Label className="text-sm font-medium">Environments</Label>
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

function ChipsSkeleton() {
  return (
    <div className="flex flex-wrap gap-2">
      {[70, 90, 60, 80].map((w, i) => (
        <Sk h={34} key={i} r={6} w={w} />
      ))}
    </div>
  )
}

function FieldSkeleton() {
  return <Sk h={38} r={6} w="100%" />
}
