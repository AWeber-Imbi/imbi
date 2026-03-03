import { useState } from 'react'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import type { ServiceAccount, ServiceAccountCreate } from '@/types'

interface ServiceAccountFormProps {
  account: ServiceAccount | null
  onSave: (data: ServiceAccountCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
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
  const [displayName, setDisplayName] = useState(
    account?.display_name || ''
  )
  const [description, setDescription] = useState(
    account?.description || ''
  )

  // Account status
  const [isActive, setIsActive] = useState(account?.is_active ?? true)

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

    setValidationErrors(errors)
    setTouched({
      slug: true,
      display_name: true,
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
            {isEditing
              ? 'Edit Service Account'
              : 'Create Service Account'}
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
            className={
              isDarkMode ? 'border-gray-600 text-gray-300' : ''
            }
          >
            <X className="w-4 h-4 mr-2" />
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoading}
            className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
          >
            <Save className="w-4 h-4 mr-2" />
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
              ? 'bg-red-900/20 border-red-700'
              : 'bg-red-50 border-red-200'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertCircle
              className={`w-5 h-5 flex-shrink-0 ${
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
                className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}
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
        className={`p-6 rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <h3
          className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Slug */}
          <div className="col-span-2">
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
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
              className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                isEditing ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
            {isEditing && (
              <p
                className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Slug cannot be changed after creation
              </p>
            )}
            {!isEditing && (
              <p
                className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Lowercase letters, numbers, and hyphens only. Must start
                with a letter.
              </p>
            )}
            {touched.slug && validationErrors.slug && (
              <p className="text-sm text-red-600 mt-1">
                {validationErrors.slug}
              </p>
            )}
          </div>

          {/* Display Name */}
          <div className="col-span-2">
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
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
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white'
                  : ''
              }
            />
            {touched.display_name &&
              validationErrors.display_name && (
                <p className="text-sm text-red-600 mt-1">
                  {validationErrors.display_name}
                </p>
              )}
          </div>

          {/* Description */}
          <div className="col-span-2">
            <label
              className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isLoading}
              placeholder="What does this service account do?"
              rows={3}
              className={`w-full px-3 py-2 rounded-md border text-sm ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400'
                  : 'bg-white border-gray-300 text-gray-900 placeholder:text-gray-500'
              } focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent`}
            />
          </div>
        </div>
      </div>

      {/* Section 2: Account Status */}
      <div
        className={`p-6 rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <h3
          className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Account Status
        </h3>

        <div>
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
              disabled={isLoading}
              className="rounded"
            />
            <span
              className={
                isDarkMode ? 'text-gray-300' : 'text-gray-700'
              }
            >
              Account Active
            </span>
          </label>
          <p
            className={`text-sm mt-1 ml-6 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Inactive service accounts cannot authenticate via API
          </p>
        </div>
      </div>
    </div>
  )
}
