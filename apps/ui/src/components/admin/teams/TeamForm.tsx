import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { IconUpload } from '../../ui/icon-upload'
import { DynamicFormFields, validateDynamicFields } from '../../ui/dynamic-fields'
import { useOrganization } from '@/contexts/OrganizationContext'
import { getTeamSchema } from '@/api/endpoints'
import type { Team, TeamCreate } from '@/types'

const BASE_TEAM_FIELDS = new Set([
  'name', 'slug', 'description', 'icon', 'icon_url',
  'organization', 'organization_slug', 'created_at', 'last_modified_at',
])

function extractDynamicFields(team: Team): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(team)) {
    if (!BASE_TEAM_FIELDS.has(key)) {
      result[key] = value
    }
  }
  return result
}

interface TeamFormProps {
  team: Team | null
  onSave: (team: TeamCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
}

export function TeamForm({
  team,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
}: TeamFormProps) {
  const isEditing = !!team
  const { selectedOrganization, organizations } = useOrganization()

  const [name, setName] = useState(team?.name || '')
  const [slug, setSlug] = useState(team?.slug || '')
  const [description, setDescription] = useState(team?.description || '')
  const [icon, setIcon] = useState(team?.icon_url || '')
  const [orgSlug, setOrgSlug] = useState(
    team?.organization.slug || selectedOrganization?.slug || ''
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [dynamicFormData, setDynamicFormData] = useState<Record<string, unknown>>(
    team ? extractDynamicFields(team) : {}
  )

  const { data: teamSchema } = useQuery({
    queryKey: ['teamSchema'],
    queryFn: getTeamSchema,
    staleTime: 5 * 60 * 1000,
  })

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Team name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9-_]+$/.test(slug)) {
      newErrors.slug = 'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'

    if (teamSchema) {
      const dynamicErrors = validateDynamicFields(teamSchema, dynamicFormData)
      Object.assign(newErrors, dynamicErrors)
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
      organization_slug: orgSlug,
      ...dynamicFormData,
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
          <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEditing ? 'Edit Team' : 'Create New Team'}
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {isEditing ? 'Update team information' : 'Create a new team'}
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
            {isLoading ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Team'}
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
                Failed to save team
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
            Team Information
          </h3>

          <div className="space-y-4">
            <div>
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                disabled={isEditing || isLoading}
                className={`w-full px-3 py-2 rounded-lg border text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 border-gray-600 text-white'
                    : 'bg-white border-gray-300 text-gray-900'
                } ${isEditing ? 'opacity-60 cursor-not-allowed' : ''} ${
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
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Team Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Platform Support Engineering"
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
                  placeholder="e.g., platform-support"
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
                placeholder="Brief description of the team's purpose"
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

            {/* Dynamic Blueprint Fields */}
            {teamSchema && (
              <DynamicFormFields
                schema={teamSchema}
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
