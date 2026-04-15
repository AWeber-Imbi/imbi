import { useState } from 'react'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { IconUpload } from '../../ui/icon-upload'
import { Card, CardContent } from '../../ui/card'
import type { Organization, OrganizationCreate } from '@/types'

interface OrganizationFormProps {
  organization: Organization | null
  onSave: (org: OrganizationCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: { response?: { data?: { detail?: string } }; message?: string } | null
}

export function OrganizationForm({
  organization,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
}: OrganizationFormProps) {
  const isEditing = !!organization

  const [name, setName] = useState(organization?.name || '')
  const [slug, setSlug] = useState(organization?.slug || '')
  const [description, setDescription] = useState(
    organization?.description || '',
  )
  const [icon, setIcon] = useState(organization?.icon || '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Organization name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9-_]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    onSave({
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(
        value
          .toLowerCase()
          .replace(/[^a-z0-9\s-_]/g, '')
          .replace(/\s+/g, '-')
          .replace(/-+/g, '-')
          .trim(),
      )
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2
            className={`text-base font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {isEditing ? 'Edit Organization' : 'Create New Organization'}
          </h2>
          <p
            className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {isEditing
              ? 'Update organization information and settings'
              : 'Create a new organization to group projects and control access'}
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
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Organization'}
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
                Failed to save organization
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
        <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
          <CardContent className="space-y-4 pt-6">
            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label
                  className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                >
                  Organization Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Engineering"
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

              {!isEditing && (
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., engineering"
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
              )}
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
                placeholder="Brief description of the organization's purpose"
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
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
