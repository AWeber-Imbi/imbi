import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getRoles } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { ServiceAccount, ServiceAccountCreate } from '@/types'

interface ServiceAccountFormProps {
  account: ServiceAccount | null
  onSave: (data: ServiceAccountCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: { response?: { data?: { detail?: string } }; message?: string } | null
}

export function ServiceAccountForm({
  account,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
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
  const { data: availableRoles = [], isLoading: rolesLoading } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  // Validation state
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

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
      slug: true,
      display_name: true,
      organization_slug: true,
      role_slug: true,
    })

    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (!validateForm()) return

    const data: ServiceAccountCreate = {
      slug: slug.trim(),
      display_name: displayName.trim(),
      description: description.trim() || null,
      is_active: isActive,
      organization_slug: organizationSlug,
      role_slug: roleSlug,
    }

    onSave(data)
  }

  const handleFieldChange = (field: string) => {
    setTouched({ ...touched, [field]: true })

    if (validationErrors[field]) {
      const newErrors = { ...validationErrors }
      delete newErrors[field]
      setValidationErrors(newErrors)
    }
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
      <div className="flex items-center justify-between">
        <div>
          <h2
            className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {isEditing ? 'Edit Service Account' : 'Create Service Account'}
          </h2>
          <p
            className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {isEditing
              ? `Editing ${account?.display_name}`
              : 'Create an automated service account for API access'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isLoading}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoading}
            className="bg-[#2A4DD0] text-white hover:bg-blue-700"
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Service Account'}
          </Button>
        </div>
      </div>

      {/* API Error Display */}
      {error && (
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-red-700 bg-red-900/20'
              : 'border-red-200 bg-red-50'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertCircle
              className={`h-5 w-5 flex-shrink-0 ${
                isDarkMode ? 'text-red-400' : 'text-red-600'
              }`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}
              >
                Failed to save service account
              </div>
              <div
                className={`mt-1 text-sm ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}
              >
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Section 1: Basic Information */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Slug */}
          <div className="col-span-2">
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Slug <span className="text-red-500">*</span>
            </label>
            <Input
              value={slug}
              onChange={(e) => handleSlugChange(e.target.value)}
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
              disabled={isEditing || isLoading}
              placeholder="my-service-account"
              className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                isEditing ? 'cursor-not-allowed opacity-60' : ''
              }`}
            />
            {isEditing && (
              <p
                className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Slug cannot be changed after creation
              </p>
            )}
            {!isEditing && (
              <p
                className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Lowercase letters, numbers, and hyphens only. Must start with a
                letter.
              </p>
            )}
            {touched.slug && validationErrors.slug && (
              <p className="mt-1 text-sm text-red-600">
                {validationErrors.slug}
              </p>
            )}
          </div>

          {/* Display Name */}
          <div className="col-span-2">
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Display Name <span className="text-red-500">*</span>
            </label>
            <Input
              value={displayName}
              onChange={(e) => {
                setDisplayName(e.target.value)
                handleFieldChange('display_name')
              }}
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
              disabled={isLoading}
              placeholder="CI/CD Pipeline"
              className={
                isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
              }
            />
            {touched.display_name && validationErrors.display_name && (
              <p className="mt-1 text-sm text-red-600">
                {validationErrors.display_name}
              </p>
            )}
          </div>

          {/* Description */}
          <div className="col-span-2">
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isLoading}
              placeholder="What does this service account do?"
              rows={3}
              className={`w-full rounded-md border px-3 py-2 text-sm ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700 text-white placeholder:text-gray-400'
                  : 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-500'
              } focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500`}
            />
          </div>
        </div>
      </div>

      {/* Section 2: Organization Membership (creation only) */}
      {!isEditing && (
        <div
          className={`rounded-lg border p-6 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <h3
            className={`font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Organization Membership
          </h3>
          <p
            className={`mb-4 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Service accounts must belong to at least one organization with a
            role to have any permissions.
          </p>

          <div className="grid grid-cols-2 gap-4">
            {/* Organization */}
            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                value={organizationSlug}
                onChange={(e) => {
                  setOrganizationSlug(e.target.value)
                  handleFieldChange('organization_slug')
                }}
                disabled={isLoading}
                className={`w-full rounded-md border px-3 py-2 text-sm ${
                  isDarkMode
                    ? 'border-gray-600 bg-gray-700 text-white'
                    : 'border-gray-300 bg-white text-gray-900'
                } focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500`}
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
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Role <span className="text-red-500">*</span>
              </label>
              {rolesLoading ? (
                <p
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Loading roles...
                </p>
              ) : (
                <select
                  value={roleSlug}
                  onChange={(e) => {
                    setRoleSlug(e.target.value)
                    handleFieldChange('role_slug')
                  }}
                  disabled={isLoading}
                  className={`w-full rounded-md border px-3 py-2 text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700 text-white'
                      : 'border-gray-300 bg-white text-gray-900'
                  } focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500`}
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
        </div>
      )}

      {/* Section 3: Account Status */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Account Status
        </h3>

        <div>
          <label className="flex cursor-pointer items-center gap-2">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              disabled={isLoading}
              className="rounded"
            />
            <span className={isDarkMode ? 'text-gray-300' : 'text-gray-700'}>
              Account Active
            </span>
          </label>
          <p
            className={`ml-6 mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Inactive service accounts cannot authenticate via API
          </p>
        </div>
      </div>
    </div>
  )
}
