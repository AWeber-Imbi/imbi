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
import { Switch } from '@/components/ui/switch'
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

interface ReleaseTrainSwitchesProps {
  canDeploy: boolean
  canPromote: boolean
  isLoading: boolean
  onChangeCanDeploy: (next: boolean) => void
  onChangeCanPromote: (next: boolean) => void
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
  const [canDeploy, setCanDeploy] = useState(environment?.can_deploy ?? true)
  const [canPromote, setCanPromote] = useState(
    environment?.can_promote ?? false,
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
      can_deploy: canDeploy,
      can_promote: canPromote,
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
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="environment-org"
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                className={`border-input bg-background text-foreground w-full rounded-lg border px-3 py-2 text-sm ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
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
                <label
                  className="text-secondary mb-1.5 block text-sm"
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
                  <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                    <AlertCircle className="size-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label
                    className="text-secondary mb-1.5 block text-sm"
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
                    <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                      <AlertCircle className="size-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
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
              <p className="text-tertiary mt-1 text-xs">
                Controls display order (lower numbers appear first)
              </p>
            </div>

            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="environment-description"
              >
                Description
              </label>
              <textarea
                className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full resize-none rounded-lg border px-3 py-2"
                disabled={isLoading}
                id="environment-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this environment"
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

            <ColorPicker
              labelValue={name}
              objectType="environment"
              onChange={setLabelColor}
              value={labelColor}
            />

            <ReleaseTrainSwitches
              canDeploy={canDeploy}
              canPromote={canPromote}
              isLoading={isLoading}
              onChangeCanDeploy={setCanDeploy}
              onChangeCanPromote={setCanPromote}
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

// Release-train flags: drive Deploy / Promote button visibility on a
// project's release train header.  Defaults mirror the backend model
// (deployable, opt-in promote).  Extracted from the main form body to
// keep ``EnvironmentForm``'s render small enough to satisfy the
// complexity audit and to make this group easy to share if another
// surface needs it later.
function ReleaseTrainSwitches({
  canDeploy,
  canPromote,
  isLoading,
  onChangeCanDeploy,
  onChangeCanPromote,
}: ReleaseTrainSwitchesProps) {
  return (
    <div>
      <p className="text-secondary mb-1.5 block text-sm">Release Train</p>
      <div className="border-input space-y-3 rounded-lg border p-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <label
              className="text-foreground text-sm font-medium"
              htmlFor="environment-can-deploy"
            >
              Allow direct deploy
            </label>
            <p className="text-tertiary text-xs">
              Show the &quot;Deploy&quot; button on the release train so
              operators can roll an explicit commit or tag into this
              environment.
            </p>
          </div>
          <Switch
            checked={canDeploy}
            disabled={isLoading}
            id="environment-can-deploy"
            onCheckedChange={onChangeCanDeploy}
          />
        </div>
        <div className="flex items-start justify-between gap-3">
          <div>
            <label
              className="text-foreground text-sm font-medium"
              htmlFor="environment-can-promote"
            >
              Allow promote
            </label>
            <p className="text-tertiary text-xs">
              Show the &quot;Promote&quot; button on the release train. Promotes
              cut a tag / GitHub Release when the source build is at a SHA, or
              trigger a Deployment when the source is already a semver tag.
            </p>
          </div>
          <Switch
            checked={canPromote}
            disabled={isLoading}
            id="environment-can-promote"
            onCheckedChange={onChangeCanPromote}
          />
        </div>
      </div>
    </div>
  )
}
