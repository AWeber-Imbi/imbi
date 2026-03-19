import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { IconUpload } from '@/components/ui/icon-upload'
import { ColorPicker } from '@/components/ui/color-picker'
import {
  DynamicFormFields,
  validateDynamicFields,
} from '@/components/ui/dynamic-fields'
import { useOrganization } from '@/contexts/OrganizationContext'
import { getEnvironmentSchema } from '@/api/endpoints'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields, slugify } from '@/lib/utils'
import type { Environment, EnvironmentCreate } from '@/types'

interface EnvironmentFormProps {
  environment: Environment | null
  onSave: (orgSlug: string, env: EnvironmentCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
}

export function EnvironmentForm({
  environment,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
}: EnvironmentFormProps) {
  const isEditing = !!environment
  const { selectedOrganization, organizations } = useOrganization()

  const [name, setName] = useState(environment?.name || '')
  const [slug, setSlug] = useState(environment?.slug || '')
  const [description, setDescription] = useState(environment?.description || '')
  const [icon, setIcon] = useState(environment?.icon || '')
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
          <h2
            className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {isEditing ? 'Edit Environment' : 'Create New Environment'}
          </h2>
          <p
            className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {isEditing
              ? 'Update environment information'
              : 'Create a new environment'}
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
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-[#2A4DD0] text-white hover:bg-blue-700"
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
              className={`h-5 w-5 flex-shrink-0 ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}
              >
                Failed to save environment
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

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <div
          className={`rounded-lg border p-6 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <h3
            className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Environment Information
          </h3>

          <div className="space-y-4">
            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                disabled={isEditing || isLoading || organizations.length <= 1}
                className={`w-full rounded-lg border px-3 py-2 text-sm ${
                  isDarkMode
                    ? 'border-gray-600 bg-gray-700 text-white'
                    : 'border-gray-300 bg-white text-gray-900'
                } ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
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
                <div
                  className={`mt-1 flex items-center gap-1 text-xs ${
                    isDarkMode ? 'text-red-400' : 'text-red-600'
                  }`}
                >
                  <AlertCircle className="h-3 w-3" />
                  {errors.organization}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Environment Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Production"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                    errors.name ? 'border-red-500' : ''
                  }`}
                />
                {errors.name && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${
                      isDarkMode ? 'text-red-400' : 'text-red-600'
                    }`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., production"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                    errors.slug ? 'border-red-500' : ''
                  }`}
                />
                {errors.slug && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${
                      isDarkMode ? 'text-red-400' : 'text-red-600'
                    }`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.slug}
                  </div>
                )}
              </div>
            </div>

            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this environment"
                className={`w-full resize-none rounded-lg border px-3 py-2 ${
                  isDarkMode
                    ? 'border-gray-600 bg-gray-700 text-white placeholder:text-gray-400'
                    : 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-500'
                }`}
              />
            </div>

            <div>
              <label
                className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Icon
              </label>
              <IconUpload
                value={icon}
                onChange={setIcon}
                isDarkMode={isDarkMode}
              />
            </div>

            <ColorPicker
              value={labelColor}
              onChange={setLabelColor}
              isDarkMode={isDarkMode}
            />

            {/* Dynamic Blueprint Fields */}
            {envSchema && (
              <DynamicFormFields
                schema={envSchema}
                data={dynamicFormData}
                errors={errors}
                onChange={handleDynamicFieldChange}
                isDarkMode={isDarkMode}
                isLoading={isLoading}
              />
            )}
          </div>
        </div>
      </form>
    </div>
  )
}
