import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle, AlertTriangle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { getRole } from '@/api/endpoints'
import type { RoleCreate } from '@/types'

interface RoleFormProps {
  roleSlug: string | null
  onSave: (role: RoleCreate) => void
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

export function RoleForm({ roleSlug, onSave, onCancel, isDarkMode, isLoading = false, error }: RoleFormProps) {
  const isEditing = !!roleSlug

  // Fetch existing role when editing
  const { data: existingRole, isLoading: roleLoading, error: roleError } = useQuery({
    queryKey: ['role', roleSlug],
    queryFn: () => getRole(roleSlug!),
    enabled: isEditing,
  })

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState(0)
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false)

  // Validation
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  // Populate form when editing
  useEffect(() => {
    if (existingRole) {
      setName(existingRole.name)
      setSlug(existingRole.slug)
      setDescription(existingRole.description || '')
      setPriority(existingRole.priority)
      setSlugManuallyEdited(true)
    }
  }, [existingRole])

  const isSystemRole = isEditing && existingRole?.is_system

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
    if (isEditing && !existingRole) return
    if (!validateForm()) return

    const roleData: RoleCreate = {
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      priority,
    }
    onSave(roleData)
  }

  const handleFieldChange = (field: string) => {
    setTouched({ ...touched, [field]: true })
    if (validationErrors[field]) {
      const newErrors = { ...validationErrors }
      delete newErrors[field]
      setValidationErrors(newErrors)
    }
  }

  if (isEditing && roleLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading role...
        </div>
      </div>
    )
  }

  if (isEditing && roleError) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load role</div>
          <div className="text-sm mt-1">
            {roleError instanceof Error ? roleError.message : 'An error occurred'}
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
            {isEditing ? 'Edit Role' : 'Create New Role'}
          </h2>
          <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {isEditing ? `Editing ${existingRole?.name || roleSlug}` : 'Define a new role for permission grouping'}
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
          {!isSystemRole && (
            <Button
              onClick={handleSave}
              disabled={isLoading}
              className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
            >
              <Save className="w-4 h-4 mr-2" />
              {isLoading ? 'Saving...' : (isEditing ? 'Save Changes' : 'Create Role')}
            </Button>
          )}
        </div>
      </div>

      {/* System Role Warning */}
      {isSystemRole && (
        <div className={`rounded-lg border p-4 ${
          isDarkMode ? 'bg-amber-900/20 border-amber-700' : 'bg-amber-50 border-amber-200'
        }`}>
          <div className="flex items-start gap-3">
            <AlertTriangle className={`w-5 h-5 flex-shrink-0 ${
              isDarkMode ? 'text-amber-400' : 'text-amber-600'
            }`} />
            <div>
              <div className={`font-medium ${isDarkMode ? 'text-amber-400' : 'text-amber-800'}`}>
                System Role
              </div>
              <div className={`text-sm mt-1 ${isDarkMode ? 'text-amber-300' : 'text-amber-700'}`}>
                This is a system role and cannot be modified. System roles are managed automatically.
              </div>
            </div>
          </div>
        </div>
      )}

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
                Failed to save role
              </div>
              <div className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}>
                {error?.response?.data?.detail || error?.message || 'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Role Details */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Role Details
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
              disabled={isLoading || isSystemRole}
              placeholder="e.g. Project Manager"
              className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                isSystemRole ? 'opacity-60 cursor-not-allowed' : ''
              }`}
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
              placeholder="e.g. project-manager"
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
              disabled={isLoading || isSystemRole}
              placeholder="Brief description of this role's purpose"
              rows={3}
              className={`w-full px-3 py-2 rounded-md border text-sm ${
                isDarkMode
                  ? 'bg-gray-700 border-gray-600 text-white placeholder-gray-400'
                  : 'bg-white border-gray-300 text-gray-900 placeholder-gray-500'
              } ${isSystemRole ? 'opacity-60 cursor-not-allowed' : ''}`}
            />
          </div>

          {/* Priority */}
          <div className="col-span-2 sm:col-span-1">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Priority
            </label>
            <Input
              type="number"
              value={priority}
              onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)}
              disabled={isLoading || isSystemRole}
              placeholder="0"
              className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                isSystemRole ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
            <p className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
              Higher priority roles take precedence. System roles use 100-1000.
            </p>
          </div>
        </div>
      </div>

      {/* Permissions Info */}
      {!isEditing && (
        <div className={`rounded-lg border p-4 ${
          isDarkMode ? 'bg-blue-900/20 border-blue-700' : 'bg-blue-50 border-blue-200'
        }`}>
          <div className="flex items-start gap-3">
            <Info className={`w-5 h-5 flex-shrink-0 ${
              isDarkMode ? 'text-blue-400' : 'text-blue-600'
            }`} />
            <div className={`text-sm ${isDarkMode ? 'text-blue-300' : 'text-blue-700'}`}>
              After creating this role, you can assign permissions to it from the role detail view.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
