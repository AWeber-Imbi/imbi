import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'

import { getRoles } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useDirtyState } from '@/hooks/useDirtyState'
import { useFormScaffold } from '@/hooks/useFormScaffold'
import type { ServiceAccount, ServiceAccountCreate } from '@/types'

interface ServiceAccountFormProps {
  account: null | ServiceAccount
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onSave: (data: ServiceAccountCreate) => void
}

export function ServiceAccountForm({
  account,
  error,
  isLoading = false,
  onCancel,
  onSave,
}: ServiceAccountFormProps) {
  const isEditing = !!account

  // Basic info
  const [slug, setSlug] = useState(account?.slug || '')
  const [displayName, setDisplayName] = useState(account?.display_name || '')
  const [description, setDescription] = useState(account?.description || '')

  // Account status
  const [isActive, setIsActive] = useState(account?.is_active ?? true)

  // Organization membership (for creation only)
  const { organizations } = useOrganization()
  const [organizationSlug, setOrganizationSlug] = useState(
    organizations.length === 1 ? organizations[0].slug : '',
  )
  const [roleSlug, setRoleSlug] = useState('')

  // Fetch available roles
  const {
    data: availableRoles = [],
    isError: rolesError,
    isLoading: rolesLoading,
  } = useQuery({
    queryFn: ({ signal }) => getRoles(signal),
    queryKey: ['roles'],
  })

  // Validation state
  const {
    handleFieldChange,
    setTouched,
    setValidationErrors,
    touched,
    validationErrors,
  } = useFormScaffold()

  // Warn on unsaved navigation. Snapshot the initial values once at mount so
  // the baseline doesn't drift when `organizations` loads asynchronously (which
  // would otherwise flip an untouched form into "dirty").
  const [initialFormData] = useState(() => ({
    description: account?.description ?? '',
    display_name: account?.display_name ?? '',
    is_active: account?.is_active ?? true,
    organization_slug: organizations.length === 1 ? organizations[0].slug : '',
    role_slug: '',
    slug: account?.slug ?? '',
  }))
  const currentFormData = {
    description,
    display_name: displayName,
    is_active: isActive,
    organization_slug: organizationSlug,
    role_slug: roleSlug,
    slug,
  }
  useDirtyState(initialFormData, currentFormData, { enabled: !isLoading })

  // Validation functions
  const validateSlug = (value: string): string => {
    if (!value.trim()) return 'Slug is required'
    if (!/^[a-z][a-z0-9-]*$/.test(value)) {
      return 'Slug must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens'
    }
    return ''
  }

  const validateDisplayName = (value: string): string => {
    if (!value.trim()) return 'Display name is required'
    return ''
  }

  // Validate all fields
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}

    const slugError = validateSlug(slug)
    if (slugError) errors.slug = slugError

    const displayNameError = validateDisplayName(displayName)
    if (displayNameError) errors.display_name = displayNameError

    if (!isEditing) {
      if (!organizationSlug)
        errors.organization_slug = 'Organization is required'
      if (!roleSlug) errors.role_slug = 'Role is required'
    }

    setValidationErrors(errors)
    setTouched({
      display_name: true,
      organization_slug: true,
      role_slug: true,
      slug: true,
    })

    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (!validateForm()) return

    const data: ServiceAccountCreate = {
      description: description.trim() || null,
      display_name: displayName.trim(),
      is_active: isActive,
      organization_slug: organizationSlug,
      role_slug: roleSlug,
      slug: slug.trim(),
    }

    onSave(data)
  }

  const handleSlugChange = (value: string) => {
    // Only allow valid slug characters
    const sanitized = value.toLowerCase().replace(/[^a-z0-9-]/g, '')
    setSlug(sanitized)
    handleFieldChange('slug')
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <FormHeader
        createLabel="Create Service Account"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing
            ? `Editing ${account?.display_name}`
            : 'Create an automated service account for API access'
        }
        title={isEditing ? 'Edit Service Account' : 'Create Service Account'}
      />

      {/* API Error Display */}
      {error && (
        <div className="rounded-lg border border-danger bg-danger p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-danger" />
            <div>
              <div className="font-medium text-danger">
                Failed to save service account
              </div>
              <div className="mt-1 text-sm text-danger">
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Section 1: Basic Information */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-2 gap-4">
            {/* Slug */}
            {!isEditing && (
              <div className="col-span-2">
                <label className="mb-1.5 block text-sm text-secondary">
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  className=""
                  disabled={isLoading}
                  onBlur={() => {
                    setTouched({ ...touched, slug: true })
                    const error = validateSlug(slug)
                    if (error) {
                      setValidationErrors({
                        ...validationErrors,
                        slug: error,
                      })
                    }
                  }}
                  onChange={(e) => handleSlugChange(e.target.value)}
                  placeholder="my-service-account"
                  value={slug}
                />
                <p className="mt-1 text-xs text-tertiary">
                  Lowercase letters, numbers, and hyphens only. Must start with
                  a letter.
                </p>
                {touched.slug && validationErrors.slug && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.slug}
                  </p>
                )}
              </div>
            )}

            {/* Display Name */}
            <div className="col-span-2">
              <label className="mb-1.5 block text-sm text-secondary">
                Display Name <span className="text-red-500">*</span>
              </label>
              <Input
                className=""
                disabled={isLoading}
                onBlur={() => {
                  setTouched({ ...touched, display_name: true })
                  const error = validateDisplayName(displayName)
                  if (error) {
                    setValidationErrors({
                      ...validationErrors,
                      display_name: error,
                    })
                  }
                }}
                onChange={(e) => {
                  setDisplayName(e.target.value)
                  handleFieldChange('display_name')
                }}
                placeholder="CI/CD Pipeline"
                value={displayName}
              />
              {touched.display_name && validationErrors.display_name && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.display_name}
                </p>
              )}
            </div>

            {/* Description */}
            <div className="col-span-2">
              <label className="mb-1.5 block text-sm text-secondary">
                Description
              </label>
              <textarea
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What does this service account do?"
                rows={3}
                value={description}
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Section 2: Organization Membership (creation only) */}
      {!isEditing && (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <p className="mb-4 text-sm text-secondary">
              Service accounts must belong to at least one organization with a
              role to have any permissions.
            </p>

            <div className="grid grid-cols-2 gap-4">
              {/* Organization */}
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Organization <span className="text-red-500">*</span>
                </label>
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                  disabled={isLoading}
                  onChange={(e) => {
                    setOrganizationSlug(e.target.value)
                    handleFieldChange('organization_slug')
                  }}
                  value={organizationSlug}
                >
                  <option value="">Select an organization...</option>
                  {organizations.map((org) => (
                    <option key={org.slug} value={org.slug}>
                      {org.name}
                    </option>
                  ))}
                </select>
                {touched.organization_slug &&
                  validationErrors.organization_slug && (
                    <p className="mt-1 text-sm text-red-600">
                      {validationErrors.organization_slug}
                    </p>
                  )}
              </div>

              {/* Role */}
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Role <span className="text-red-500">*</span>
                </label>
                {rolesLoading ? (
                  <p className="text-sm text-secondary">Loading roles...</p>
                ) : rolesError ? (
                  <p className="text-sm text-danger">
                    Failed to load roles. Please refresh and try again.
                  </p>
                ) : (
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                    disabled={isLoading}
                    onChange={(e) => {
                      setRoleSlug(e.target.value)
                      handleFieldChange('role_slug')
                    }}
                    value={roleSlug}
                  >
                    <option value="">Select a role...</option>
                    {availableRoles.map((role) => (
                      <option key={role.slug} value={role.slug}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                )}
                {touched.role_slug && validationErrors.role_slug && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.role_slug}
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Section 3: Account Status */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div>
            <label className="flex cursor-pointer items-center gap-2">
              <input
                checked={isActive}
                className="rounded"
                disabled={isLoading}
                onChange={(e) => setIsActive(e.target.checked)}
                type="checkbox"
              />
              <span className="text-secondary">Account Active</span>
            </label>
            <p className="ml-6 mt-1 text-sm text-secondary">
              Inactive service accounts cannot authenticate via API
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
