import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getGroup } from '@/api/endpoints'
import type { GroupCreate } from '@/types'

interface GroupFormProps {
  groupSlug: string | null
  onSave: (group: GroupCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
}

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

export function GroupForm({ groupSlug, onSave, onCancel, isDarkMode, isLoading = false, error }: GroupFormProps) {
  const isEditing = !!groupSlug

  const { data: existingGroup, isLoading: groupLoading, error: groupError } = useQuery({
    queryKey: ['group', groupSlug],
    queryFn: () => getGroup(groupSlug!),
    enabled: isEditing,
  })

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [icon, setIcon] = useState('')
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false)

  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  useEffect(() => {
    if (existingGroup) {
      setName(existingGroup.name)
      setSlug(existingGroup.slug)
      setDescription(existingGroup.description || '')
      setIcon(existingGroup.icon_url || '')
      setSlugManuallyEdited(true)
    }
  }, [existingGroup])

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing && !slugManuallyEdited) {
      setSlug(toSlug(value))
    }
    handleFieldChange('name')
  }

  const handleSlugChange = (value: string) => {
    setSlug(toSlug(value))
    setSlugManuallyEdited(true)
    handleFieldChange('slug')
  }

  const validateName = (value: string): string => {
    if (!value.trim()) return 'Name is required'
    return ''
  }

  const validateSlug = (value: string): string => {
    if (!value.trim()) return 'Slug is required'
    if (!/^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/.test(value)) {
      return 'Slug must contain only lowercase letters, numbers, and hyphens'
    }
    return ''
  }

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}
    const nameError = validateName(name)
    if (nameError) errors.name = nameError
    const slugError = validateSlug(slug)
    if (slugError) errors.slug = slugError

    setValidationErrors(errors)
    setTouched({ name: true, slug: true })
    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (isEditing && !existingGroup) return
    if (!validateForm()) return

    const groupData: GroupCreate = {
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
    }
    onSave(groupData)
  }

  const handleFieldChange = (field: string) => {
    setTouched({ ...touched, [field]: true })
    if (validationErrors[field]) {
      const newErrors = { ...validationErrors }
      delete newErrors[field]
      setValidationErrors(newErrors)
    }
  }

  if (isEditing && groupLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading group...
        </div>
      </div>
    )
  }

  if (isEditing && groupError) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load group</div>
          <div className="text-sm mt-1">
            {groupError instanceof Error ? groupError.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEditing ? 'Edit Group' : 'Create New Group'}
          </h2>
          <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {isEditing ? `Editing ${existingGroup?.name || groupSlug}` : 'Create a new group to organize users'}
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
            onClick={handleSave}
            disabled={isLoading}
            className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
          >
            <Save className="w-4 h-4 mr-2" />
            {isLoading ? 'Saving...' : (isEditing ? 'Save Changes' : 'Create Group')}
          </Button>
        </div>
      </div>

      {/* API Error Display */}
      {error && (
        <div className={`rounded-lg border p-4 ${
          isDarkMode ? 'bg-red-900/20 border-red-700' : 'bg-red-50 border-red-200'
        }`}>
          <div className="flex items-start gap-3">
            <AlertCircle className={`w-5 h-5 flex-shrink-0 ${
              isDarkMode ? 'text-red-400' : 'text-red-600'
            }`} />
            <div>
              <div className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}>
                Failed to save group
              </div>
              <div className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}>
                {error?.response?.data?.detail || error?.message || 'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Basic Information */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Name */}
          <div className="col-span-2">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Name <span className="text-red-500">*</span>
            </label>
            <Input
              value={name}
              onChange={(e) => handleNameChange(e.target.value)}
              onBlur={() => {
                setTouched({ ...touched, name: true })
                const err = validateName(name)
                if (err) setValidationErrors({ ...validationErrors, name: err })
              }}
              disabled={isLoading}
              placeholder="e.g., Engineering, Platform Support"
              className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
            {touched.name && validationErrors.name && (
              <p className="text-sm text-red-600 mt-1">{validationErrors.name}</p>
            )}
          </div>

          {/* Slug */}
          <div className="col-span-2">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Slug <span className="text-red-500">*</span>
            </label>
            <Input
              value={slug}
              onChange={(e) => handleSlugChange(e.target.value)}
              onBlur={() => {
                setTouched({ ...touched, slug: true })
                const err = validateSlug(slug)
                if (err) setValidationErrors({ ...validationErrors, slug: err })
              }}
              disabled={isLoading || isEditing}
              placeholder="e.g., engineering, platform-support"
              className={`font-mono ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                isEditing ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
            {isEditing && (
              <p className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                Slug cannot be changed after creation
              </p>
            )}
            {!isEditing && !slugManuallyEdited && name && (
              <p className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                Auto-generated from name
              </p>
            )}
            {touched.slug && validationErrors.slug && (
              <p className="text-sm text-red-600 mt-1">{validationErrors.slug}</p>
            )}
          </div>

          {/* Description */}
          <div className="col-span-2">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={isLoading}
              placeholder="Brief description of the group's purpose"
              rows={3}
              className={`w-full px-3 py-2 rounded-md border text-sm ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
                  : 'bg-white border-gray-300 text-gray-900 placeholder-gray-500'
              }`}
            />
          </div>

          {/* Icon */}
          <div className="col-span-2">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Icon
            </label>
            <Input
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              disabled={isLoading}
              placeholder="URL or CSS class name (optional)"
              className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
            />
            <p className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              Icon URL or CSS class for group identification
            </p>
          </div>
        </div>
      </div>

      {/* Roles Info */}
      {!isEditing && (
        <div className={`rounded-lg border p-4 ${
          isDarkMode ? 'bg-blue-900/20 border-blue-700' : 'bg-blue-50 border-blue-200'
        }`}>
          <div className="flex items-start gap-3">
            <Info className={`w-5 h-5 flex-shrink-0 ${
              isDarkMode ? 'text-blue-400' : 'text-blue-600'
            }`} />
            <div className={`text-sm ${isDarkMode ? 'text-blue-300' : 'text-blue-700'}`}>
              After creating this group, you can assign roles and view members from the group detail view.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
