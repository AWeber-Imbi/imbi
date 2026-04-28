import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'

import { getEnvironmentSchema } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Card, CardContent } from '@/components/ui/card'
import { ColorPicker } from '@/components/ui/color-picker'
import {
  DynamicFormFields,
  validateDynamicFields,
} from '@/components/ui/dynamic-fields'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields, slugify } from '@/lib/utils'
import type { Environment, EnvironmentCreate } from '@/types'

interface EnvironmentFormProps {
  environment: Environment | null
  error?: unknown
  isLoading?: boolean
  onCancel: () => void
  onSave: (orgSlug: string, env: EnvironmentCreate) => void
}

export function EnvironmentForm({
  environment,
  error,
  isLoading = false,
  onCancel,
  onSave,
}: EnvironmentFormProps) {
  const isEditing = !!environment
  const { organizations, selectedOrganization } = useOrganization()

  const [name, setName] = useState(environment?.name || '')
  const [slug, setSlug] = useState(environment?.slug || '')
  const [sortOrder, setSortOrder] = useState(
    String(environment?.sort_order ?? 0),
  )
  const [description, setDescription] = useState(environment?.description || '')
  const [icon, setIcon] = useState(environment?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [labelColor, setLabelColor] = useState(environment?.label_color ?? '')
  const [orgSlug, setOrgSlug] = useState(
    environment?.organization.slug || selectedOrganization?.slug || '',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dynamicFormData, setDynamicFormData] = useState<
    Record<string, unknown>
  >(
    environment
      ? extractDynamicFields(environment, ENVIRONMENT_BASE_FIELDS_SET)
      : {},
  )

  const { data: envSchema } = useQuery({
    queryFn: ({ signal }) => getEnvironmentSchema(signal),
    queryKey: ['environmentSchema'],
    staleTime: 5 * 60 * 1000,
  })

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Environment name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'

    if (envSchema) {
      const dynamicErrors = validateDynamicFields(envSchema, dynamicFormData)
      Object.assign(newErrors, dynamicErrors)
    }

    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSave = () => {
    if (!validate()) return

    onSave(orgSlug, {
      description: description.trim() || null,
      icon: icon.trim() || null,
      label_color: /^#[0-9A-Fa-f]{6}$/.test(labelColor)
        ? labelColor.toUpperCase()
        : null,
      name: name.trim(),
      slug: slug.trim(),
      sort_order: parseInt(sortOrder, 10) || 0,
      ...dynamicFormData,
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    handleSave()
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
      <FormHeader
        createLabel="Create Environment"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing
            ? 'Update environment information'
            : 'Create a new environment'
        }
        title={isEditing ? 'Edit Environment' : 'Create New Environment'}
      />

      {/* API Error */}
      {!!error && (
        <ErrorBanner error={error} title="Failed to save environment" />
      )}

      {/* Form */}
      <form className="space-y-6" onSubmit={handleSubmit}>
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div>
              <label
                className="mb-1.5 block text-sm text-secondary"
                htmlFor="environment-org"
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                className={`w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
                  errors.organization ? 'border-red-500' : ''
                }`}
                disabled={isEditing || isLoading || organizations.length <= 1}
                id="environment-org"
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
                <label
                  className="mb-1.5 block text-sm text-secondary"
                  htmlFor="environment-name"
                >
                  Environment Name <span className="text-red-500">*</span>
                </label>
                <Input
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                  disabled={isLoading}
                  id="environment-name"
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Production"
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
                  <label
                    className="mb-1.5 block text-sm text-secondary"
                    htmlFor="environment-slug"
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                    disabled={isLoading}
                    id="environment-slug"
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., production"
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
              <label
                className="mb-1.5 block text-sm text-secondary"
                htmlFor="environment-sort-order"
              >
                Sort Order
              </label>
              <Input
                className="w-32"
                disabled={isLoading}
                id="environment-sort-order"
                onChange={(e) => setSortOrder(e.target.value)}
                placeholder="0"
                type="number"
                value={sortOrder}
              />
              <p className="mt-1 text-xs text-tertiary">
                Controls display order (lower numbers appear first)
              </p>
            </div>

            <div>
              <label
                className="mb-1.5 block text-sm text-secondary"
                htmlFor="environment-description"
              >
                Description
              </label>
              <textarea
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
                disabled={isLoading}
                id="environment-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this environment"
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

            <ColorPicker
              labelValue={name}
              objectType="environment"
              onChange={setLabelColor}
              value={labelColor}
            />

            {/* Dynamic Blueprint Fields */}
            {envSchema && (
              <DynamicFormFields
                data={dynamicFormData}
                errors={errors}
                isLoading={isLoading}
                onChange={handleDynamicFieldChange}
                schema={envSchema}
              />
            )}
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
