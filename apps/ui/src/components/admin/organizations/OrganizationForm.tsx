import { useState } from 'react'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { IconUpload } from '../../ui/icon-upload'
import type { Organization, OrganizationCreate } from '@/types'

interface OrganizationFormProps {
  organization: Organization | null
  onSave: (org: OrganizationCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
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
  const [description, setDescription] = useState(organization?.description || '')
  const [icon, setIcon] = useState(organization?.icon_url || '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Organization name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9-_]+$/.test(slug)) {
      newErrors.slug = 'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
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
      icon_url: icon.trim() || null,
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
          .trim()
      )
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEditing ? 'Edit Organization' : 'Create New Organization'}
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
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
            <X className="w-4 h-4 mr-2" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
          >
            <Save className="w-4 h-4 mr-2" />
            {isLoading ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Organization'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {error && (
        <div className={`rounded-lg border p-4 ${
          isDarkMode ? 'bg-red-900/20 border-red-700' : 'bg-red-50 border-red-200'
        }`}>
          <div className="flex items-start gap-3">
            <AlertCircle className={`w-5 h-5 flex-shrink-0 ${isDarkMode ? 'text-red-400' : 'text-red-600'}`} />
            <div>
              <div className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}>
                Failed to save organization
              </div>
              <div className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}>
                {error?.response?.data?.detail || error?.message || 'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <div className={`p-6 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Organization Information
          </h3>

          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Organization Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Engineering"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                    errors.name ? 'border-red-500' : ''
                  }`}
                />
                {errors.name && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${
                    isDarkMode ? 'text-red-400' : 'text-red-600'
                  }`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., engineering"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                    errors.slug ? 'border-red-500' : ''
                  }`}
                />
                {errors.slug && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${
                    isDarkMode ? 'text-red-400' : 'text-red-600'
                  }`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.slug}
                  </div>
                )}
              </div>
            </div>

            <div>
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of the organization's purpose"
                className={`w-full px-3 py-2 rounded-lg border resize-none ${
                  isDarkMode
                    ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400'
                    : 'bg-white border-gray-300 text-gray-900 placeholder:text-gray-500'
                }`}
              />
            </div>

            <div>
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Icon
              </label>
              <IconUpload value={icon} onChange={setIcon} isDarkMode={isDarkMode} />
            </div>
          </div>
        </div>
      </form>
    </div>
  )
}
