import { useState } from 'react'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { IconUpload } from '@/components/ui/icon-upload'
import { useOrganization } from '@/contexts/OrganizationContext'
import { slugify } from '@/lib/utils'
import type { LinkDefinition, LinkDefinitionCreate } from '@/types'

interface LinkDefinitionFormProps {
  linkDefinition: LinkDefinition | null
  onSave: (orgSlug: string, data: LinkDefinitionCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
}

export function LinkDefinitionForm({
  linkDefinition,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
}: LinkDefinitionFormProps) {
  const isEditing = !!linkDefinition
  const { selectedOrganization, organizations } = useOrganization()

  const [name, setName] = useState(linkDefinition?.name || '')
  const [slug, setSlug] = useState(linkDefinition?.slug || '')
  const [description, setDescription] = useState(linkDefinition?.description || '')
  const [icon, setIcon] = useState(linkDefinition?.icon || '')
  const [urlTemplate, setUrlTemplate] = useState(linkDefinition?.url_template || '')
  const [orgSlug, setOrgSlug] = useState(
    linkDefinition?.organization?.slug || selectedOrganization?.slug || ''
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug = 'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'
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
      url_template: urlTemplate.trim() || null,
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEditing ? 'Edit Link Definition' : 'Create New Link Definition'}
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {isEditing ? 'Update link definition information' : 'Create a new link definition'}
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
            {isLoading ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Link Definition'}
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
                Failed to save link definition
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
            Link Definition Information
          </h3>

          <div className="space-y-4">
            <div>
              <label htmlFor="link-def-org" className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                id="link-def-org"
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                disabled={isEditing || isLoading || organizations.length <= 1}
                className={`w-full px-3 py-2 rounded-lg border text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 border-gray-600 text-white'
                    : 'bg-white border-gray-300 text-gray-900'
                } ${isEditing || isLoading || organizations.length <= 1 ? 'opacity-60 cursor-not-allowed' : ''} ${
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
                <div className={`flex items-center gap-1 mt-1 text-xs ${
                  isDarkMode ? 'text-red-400' : 'text-red-600'
                }`}>
                  <AlertCircle className="w-3 h-3" />
                  {errors.organization}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label htmlFor="link-def-name" className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  id="link-def-name"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., GitHub Repository"
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
                <label htmlFor="link-def-slug" className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  id="link-def-slug"
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., github-repository"
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
              <label htmlFor="link-def-description" className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Description
              </label>
              <textarea
                id="link-def-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this link definition"
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

            <div>
              <label htmlFor="link-def-url-template" className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                URL Template
              </label>
              <Input
                id="link-def-url-template"
                value={urlTemplate}
                onChange={(e) => setUrlTemplate(e.target.value)}
                placeholder='e.g., https://github.com/{organization}/{project}'
                disabled={isLoading}
                className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
              />
              <p className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                URL template with placeholders in curly braces
              </p>
            </div>
          </div>
        </div>
      </form>
    </div>
  )
}
