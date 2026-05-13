import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Save, X } from 'lucide-react'

import { getProjectTypeSchema } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  DynamicFormFields,
  validateDynamicFields,
} from '@/components/ui/dynamic-fields'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { PROJECT_TYPE_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields, slugify } from '@/lib/utils'
import type { ProjectType, ProjectTypeCreate } from '@/types'

interface ProjectTypeFormProps {
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onSave: (orgSlug: string, pt: ProjectTypeCreate) => void
  projectType: null | ProjectType
}

export function ProjectTypeForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  projectType,
}: ProjectTypeFormProps) {
  const isEditing = !!projectType
  const { organizations, selectedOrganization } = useOrganization()

  const [name, setName] = useState(projectType?.name || '')
  const [slug, setSlug] = useState(projectType?.slug || '')
  const [description, setDescription] = useState(projectType?.description || '')
  const [icon, setIcon] = useState(projectType?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [orgSlug, setOrgSlug] = useState(
    projectType?.organization.slug || selectedOrganization?.slug || '',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dynamicFormData, setDynamicFormData] = useState<
    Record<string, unknown>
  >(
    projectType
      ? extractDynamicFields(projectType, PROJECT_TYPE_BASE_FIELDS_SET)
      : {},
  )

  const { data: ptSchema } = useQuery({
    queryFn: ({ signal }) => getProjectTypeSchema(signal),
    queryKey: ['projectTypeSchema'],
    staleTime: 5 * 60 * 1000,
  })

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Project type name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'

    if (ptSchema) {
      const dynamicErrors = validateDynamicFields(ptSchema, dynamicFormData)
      Object.assign(newErrors, dynamicErrors)
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    onSave(orgSlug, {
      description: description.trim() || null,
      icon: icon.trim() || null,
      name: name.trim(),
      slug: slug.trim(),
      ...dynamicFormData,
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  const handleDynamicFieldChange = (key: string, value: unknown) => {
    setDynamicFormData((prev) => ({ ...prev, [key]: value }))
    if (errors[key]) {
      setErrors((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-primary text-base font-medium">
            {isEditing ? 'Edit Project Type' : 'Create New Project Type'}
          </h2>
          <p className="text-secondary mt-1 text-sm">
            {isEditing
              ? 'Update project type information'
              : 'Create a new project type'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button disabled={isLoading} onClick={onCancel} variant="outline">
            <X className="mr-2 size-4" />
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading}
            onClick={handleSubmit}
          >
            <Save className="mr-2 size-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Project Type'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {error && (
        <div className="border-danger bg-danger rounded-lg border p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="text-danger size-5 shrink-0" />
            <div>
              <div className="text-danger font-medium">
                Failed to save project type
              </div>
              <div className="text-danger mt-1 text-sm">
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form className="space-y-6" onSubmit={handleSubmit}>
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                className={`border-input bg-background text-foreground w-full rounded-lg border px-3 py-2 text-sm ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
                  errors.organization ? 'border-red-500' : ''
                }`}
                disabled={isEditing || isLoading || organizations.length <= 1}
                onChange={(e) => setOrgSlug(e.target.value)}
                value={orgSlug}
              >
                <option value="">Select organization...</option>
                {organizations.map((org) => (
                  <option key={org.slug} value={org.slug}>
                    {org.name}
                  </option>
                ))}
              </select>
              {errors.organization && (
                <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                  <AlertCircle className="size-3" />
                  {errors.organization}
                </div>
              )}
            </div>

            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label className="text-secondary mb-1.5 block text-sm">
                  Project Type Name <span className="text-red-500">*</span>
                </label>
                <Input
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., REST API"
                  value={name}
                />
                {errors.name && (
                  <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                    <AlertCircle className="size-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label className="text-secondary mb-1.5 block text-sm">
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                    disabled={isLoading}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., rest-api"
                    value={slug}
                  />
                  {errors.slug && (
                    <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                      <AlertCircle className="size-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Description
              </label>
              <textarea
                className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full resize-none rounded-lg border px-3 py-2"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this project type"
                rows={3}
                value={description}
              />
            </div>

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Icon
              </label>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <p className="text-tertiary mb-1.5 text-xs">Pick an icon</p>
                  <IconPicker
                    onChange={handleIconChange}
                    value={
                      !icon.startsWith('/') && !icon.startsWith('http')
                        ? icon
                        : ''
                    }
                  />
                </div>
                <div>
                  <p className="text-tertiary mb-1.5 text-xs">
                    Or upload a custom image
                  </p>
                  <IconUpload
                    onChange={handleIconChange}
                    value={
                      icon.startsWith('/') || icon.startsWith('http')
                        ? icon
                        : ''
                    }
                  />
                </div>
              </div>
            </div>

            {/* Dynamic Blueprint Fields */}
            {ptSchema && (
              <DynamicFormFields
                data={dynamicFormData}
                errors={errors}
                isLoading={isLoading}
                onChange={handleDynamicFieldChange}
                schema={ptSchema}
              />
            )}
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
