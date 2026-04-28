import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Save, X } from 'lucide-react'

import { getTeamSchema } from '@/api/endpoints'
import { Card, CardContent } from '@/components/ui/card'
import { IconPicker } from '@/components/ui/icon-picker'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { TEAM_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields, slugify } from '@/lib/utils'
import type { Team, TeamCreate } from '@/types'

import { Button } from '../../ui/button'
import {
  DynamicFormFields,
  validateDynamicFields,
} from '../../ui/dynamic-fields'
import { IconUpload } from '../../ui/icon-upload'
import { Input } from '../../ui/input'

interface TeamFormProps {
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onSave: (orgSlug: string, team: TeamCreate) => void
  team: null | Team
}

export function TeamForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  team,
}: TeamFormProps) {
  const isEditing = !!team
  const { organizations, selectedOrganization } = useOrganization()

  const [name, setName] = useState(team?.name || '')
  const [slug, setSlug] = useState(team?.slug || '')
  const [description, setDescription] = useState(team?.description || '')
  const [icon, setIcon] = useState(team?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [orgSlug, setOrgSlug] = useState(
    team?.organization.slug || selectedOrganization?.slug || '',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dynamicFormData, setDynamicFormData] = useState<
    Record<string, unknown>
  >(team ? extractDynamicFields(team, TEAM_BASE_FIELDS_SET) : {})

  const { data: teamSchema } = useQuery({
    queryFn: ({ signal }) => getTeamSchema(signal),
    queryKey: ['teamSchema'],
    staleTime: 5 * 60 * 1000,
  })

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Team name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9-_]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'

    if (teamSchema) {
      const dynamicErrors = validateDynamicFields(teamSchema, dynamicFormData)
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
          <h2 className="text-base font-medium text-primary">
            {isEditing ? 'Edit Team' : 'Create New Team'}
          </h2>
          <p className="mt-1 text-sm text-secondary">
            {isEditing ? 'Update team information' : 'Create a new team'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button disabled={isLoading} onClick={onCancel} variant="outline">
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading}
            onClick={handleSubmit}
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Team'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {error && (
        <div className="rounded-lg border border-danger bg-danger p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-danger" />
            <div>
              <div className="font-medium text-danger">Failed to save team</div>
              <div className="mt-1 text-sm text-danger">
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
              <label className="mb-1.5 block text-sm text-secondary">
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                className={`w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
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
                <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                  <AlertCircle className="h-3 w-3" />
                  {errors.organization}
                </div>
              )}
            </div>

            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Team Name <span className="text-red-500">*</span>
                </label>
                <Input
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Platform Support Engineering"
                  value={name}
                />
                {errors.name && (
                  <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label className="mb-1.5 block text-sm text-secondary">
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                    disabled={isLoading}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., platform-support"
                    value={slug}
                  />
                  {errors.slug && (
                    <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                      <AlertCircle className="h-3 w-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Description
              </label>
              <textarea
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of the team's purpose"
                rows={3}
                value={description}
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Icon
              </label>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">Pick an icon</p>
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
                  <p className="mb-1.5 text-xs text-tertiary">
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
            {teamSchema && (
              <DynamicFormFields
                data={dynamicFormData}
                errors={errors}
                isLoading={isLoading}
                onChange={handleDynamicFieldChange}
                schema={teamSchema}
              />
            )}
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
