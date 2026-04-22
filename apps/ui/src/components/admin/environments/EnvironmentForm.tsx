import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconUpload } from '@/components/ui/icon-upload'
import { IconPicker } from '@/components/ui/icon-picker'
import { ColorPicker } from '@/components/ui/color-picker'
import {
  DynamicFormFields,
  validateDynamicFields,
} from '@/components/ui/dynamic-fields'
import { useOrganization } from '@/contexts/OrganizationContext'
import { getEnvironmentSchema } from '@/api/endpoints'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { extractDynamicFields, slugify } from '@/lib/utils'
import type { Environment, EnvironmentCreate } from '@/types'

interface EnvironmentFormProps {
  environment: Environment | null
  onSave: (orgSlug: string, env: EnvironmentCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: unknown
}

export function EnvironmentForm({
  environment,
  onSave,
  onCancel,
  isLoading = false,
  error,
}: EnvironmentFormProps) {
  const isEditing = !!environment
  const { selectedOrganization, organizations } = useOrganization()

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
    queryKey: ['environmentSchema'],
    queryFn: getEnvironmentSchema,
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    onSave(orgSlug, {
      name: name.trim(),
      slug: slug.trim(),
      sort_order: parseInt(sortOrder, 10) || 0,
      description: description.trim() || null,
      icon: icon.trim() || null,
      label_color: /^#[0-9A-Fa-f]{6}$/.test(labelColor)
        ? labelColor.toUpperCase()
        : null,
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
            {isEditing ? 'Edit Environment' : 'Create New Environment'}
          </h2>
          <p className="mt-1 text-sm text-secondary">
            {isEditing
              ? 'Update environment information'
              : 'Create a new environment'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Environment'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {!!error && (
        <ErrorBanner title="Failed to save environment" error={error} />
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div>
              <label
                htmlFor="environment-org"
                className="mb-1.5 block text-sm text-secondary"
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                id="environment-org"
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                disabled={isEditing || isLoading || organizations.length <= 1}
                className={`w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
                  errors.organization ? 'border-red-500' : ''
                }`}
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
                  htmlFor="environment-name"
                  className="mb-1.5 block text-sm text-secondary"
                >
                  Environment Name <span className="text-red-500">*</span>
                </label>
                <Input
                  id="environment-name"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Production"
                  disabled={isLoading}
                  className={` ${errors.name ? 'border-red-500' : ''}`}
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
                    htmlFor="environment-slug"
                    className="mb-1.5 block text-sm text-secondary"
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    id="environment-slug"
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., production"
                    disabled={isLoading}
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
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
                htmlFor="environment-sort-order"
                className="mb-1.5 block text-sm text-secondary"
              >
                Sort Order
              </label>
              <Input
                id="environment-sort-order"
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                placeholder="0"
                disabled={isLoading}
                className="w-32"
              />
              <p className="mt-1 text-xs text-tertiary">
                Controls display order (lower numbers appear first)
              </p>
            </div>

            <div>
              <label
                htmlFor="environment-description"
                className="mb-1.5 block text-sm text-secondary"
              >
                Description
              </label>
              <textarea
                id="environment-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this environment"
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
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
                    value={
                      !icon.startsWith('/') && !icon.startsWith('http')
                        ? icon
                        : ''
                    }
                    onChange={handleIconChange}
                  />
                </div>
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">
                    Or upload a custom image
                  </p>
                  <IconUpload
                    value={
                      icon.startsWith('/') || icon.startsWith('http')
                        ? icon
                        : ''
                    }
                    onChange={handleIconChange}
                  />
                </div>
              </div>
            </div>

            <ColorPicker
              value={labelColor}
              onChange={setLabelColor}
              objectType="environment"
              labelValue={name}
            />

            {/* Dynamic Blueprint Fields */}
            {envSchema && (
              <DynamicFormFields
                schema={envSchema}
                data={dynamicFormData}
                errors={errors}
                onChange={handleDynamicFieldChange}
                isLoading={isLoading}
              />
            )}
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
