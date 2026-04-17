import { useState, useMemo, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useOrganization } from '@/contexts/OrganizationContext'
import { updateProject, getProjectSchema, listTeams } from '@/api/endpoints'
import type { DynamicSchema, DynamicFieldSchema } from '@/api/endpoints'
import type { Project } from '@/types'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Card } from '@/components/ui/card'
import {
  DynamicFormFields,
  validateDynamicFields,
} from '@/components/ui/dynamic-fields'
import { PROJECT_BASE_FIELDS_SET } from '@/lib/constants'

interface EditProjectFormProps {
  project: Project
}

export function EditProjectForm({ project }: EditProjectFormProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()

  const [name, setName] = useState(project.name)
  const [description, setDescription] = useState(project.description ?? '')
  const [teamSlug, setTeamSlug] = useState(project.team.slug)
  const [dynamicData, setDynamicData] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})

  const {
    data: teams = [],
    isLoading: teamsLoading,
    isError: teamsError,
  } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: () => listTeams(orgSlug),
    enabled: !!orgSlug,
  })

  const {
    data: projectSchema,
    isLoading: schemaLoading,
    isError: schemaError,
  } = useQuery({
    queryKey: ['projectSchema', orgSlug, project.id],
    queryFn: () => getProjectSchema(orgSlug, project.id),
    enabled: !!orgSlug,
  })

  // Flatten schema sections into editable fields only, skipping base and non-editable fields
  const editableSchema = useMemo<DynamicSchema>(() => {
    if (!projectSchema) return { properties: {} }
    const properties: Record<string, DynamicFieldSchema> = {}
    const seen = new Set<string>()
    for (const section of projectSchema.sections) {
      for (const [key, def] of Object.entries(section.properties)) {
        if (PROJECT_BASE_FIELDS_SET.has(key) || seen.has(key)) continue
        seen.add(key)
        if (def['x-ui']?.editable === false) continue
        properties[key] = {
          type: def.type ?? undefined,
          format: def.format ?? undefined,
          title: def.title ?? undefined,
          description: def.description ?? undefined,
          enum: def.enum ?? undefined,
          default: def.default,
          minimum: def.minimum ?? undefined,
          maximum: def.maximum ?? undefined,
        }
      }
    }
    return { properties }
  }, [projectSchema])

  // Sync form state when project data changes (e.g. after a successful save)
  useEffect(() => {
    setName(project.name)
    setDescription(project.description ?? '')
    setTeamSlug(project.team.slug)
    const initial: Record<string, unknown> = {}
    for (const key of Object.keys(editableSchema.properties)) {
      if (project[key] !== undefined) {
        initial[key] = project[key]
      }
    }
    setDynamicData(initial)
  }, [editableSchema, project])

  const mutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      updateProject(orgSlug, project.id, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['project', orgSlug, project.id],
      })
    },
  })

  const isLoading = teamsLoading || schemaLoading
  const isDataError = teamsError || schemaError

  const handleSave = () => {
    const newErrors: Record<string, string> = {}

    if (!name.trim()) {
      newErrors.name = 'Name is required'
    }

    const dynamicErrors = validateDynamicFields(editableSchema, dynamicData)
    Object.assign(newErrors, dynamicErrors)

    if (Object.keys(newErrors).length > 0) {
      setErrors(newErrors)
      return
    }

    setErrors({})
    mutation.mutate({
      name: name.trim(),
      description: description.trim() || null,
      team_slug: teamSlug,
      ...dynamicData,
    })
  }

  const inputClass = ''
  const labelClass = 'mb-1.5 block text-sm text-secondary'

  if (isLoading) {
    return (
      <Card className={'p-6'}>
        <h3 className={'mb-4 text-primary'}>Project Details</h3>
        <p className={'text-sm text-tertiary'}>Loading...</p>
      </Card>
    )
  }

  if (isDataError) {
    return (
      <Card className={'p-6'}>
        <h3 className={'mb-4 text-primary'}>Project Details</h3>
        <p className="text-sm text-red-600 dark:text-red-400">
          Failed to load form data. Please try refreshing the page.
        </p>
      </Card>
    )
  }

  return (
    <Card className={'p-6'}>
      <h3 className={'mb-4 text-primary'}>Project Details</h3>

      <div className="space-y-4">
        <div>
          <label className={labelClass}>
            Name <span className="text-red-500">*</span>
          </label>
          <Input
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={mutation.isPending}
            className={`${inputClass} ${errors.name ? 'border-red-500' : ''}`}
          />
          {errors.name && (
            <p className="mt-1 text-xs text-red-600 dark:text-red-400">
              {errors.name}
            </p>
          )}
        </div>

        <div>
          <label className={labelClass}>Description</label>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            disabled={mutation.isPending}
            rows={3}
            className={inputClass}
          />
        </div>

        <div>
          <label className={labelClass}>Team</label>
          <select
            value={teamSlug}
            onChange={(e) => setTeamSlug(e.target.value)}
            disabled={mutation.isPending || teamsLoading}
            className={`w-full rounded-lg border px-3 py-2 text-sm ${'border-input bg-background text-foreground'}`}
          >
            {teams.map((t) => (
              <option key={t.slug} value={t.slug}>
                {t.name}
              </option>
            ))}
          </select>
        </div>

        <DynamicFormFields
          schema={editableSchema}
          data={dynamicData}
          errors={errors}
          onChange={(key, value) =>
            setDynamicData((prev) => ({ ...prev, [key]: value }))
          }
          isLoading={mutation.isPending}
        />
      </div>

      {mutation.isError && (
        <p className="mt-4 text-center text-sm text-red-600 dark:text-red-400">
          Failed to save. Please try again.
        </p>
      )}

      <div className="mt-4 flex justify-end">
        <Button
          size="sm"
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={handleSave}
          disabled={mutation.isPending}
        >
          {mutation.isPending ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}
