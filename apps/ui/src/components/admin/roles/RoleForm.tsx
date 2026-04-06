import { useState, useEffect, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Save,
  X,
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import { getRole, getAdminSettings } from '@/api/endpoints'
import type { RoleCreate, Permission } from '@/types'

interface RoleFormProps {
  roleSlug: string | null
  onSave: (role: RoleCreate, permissions: string[]) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: { response?: { data?: { detail?: string } }; message?: string } | null
}

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}

// Group permissions by resource_type dynamically
function groupPermissionsByResource(
  permissions: Permission[],
): Record<string, Permission[]> {
  const grouped: Record<string, Permission[]> = {}
  for (const perm of permissions) {
    const key = perm.resource_type
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(perm)
  }
  return grouped
}

// Generate a human-readable label from a resource_type key
function resourceLabel(resource: string): string {
  return (
    resource
      .split(/[-_]/)
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ') + ' Management'
  )
}

export function RoleForm({
  roleSlug,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
}: RoleFormProps) {
  const isEditing = !!roleSlug

  // Fetch existing role when editing
  const {
    data: existingRole,
    isLoading: roleLoading,
    error: roleError,
  } = useQuery({
    queryKey: ['role', roleSlug],
    queryFn: () => getRole(roleSlug!),
    enabled: isEditing,
  })

  // Fetch available permissions
  const {
    data: adminSettings,
    isLoading: adminSettingsLoading,
    error: adminSettingsError,
  } = useQuery({
    queryKey: ['adminSettings'],
    queryFn: getAdminSettings,
  })

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [priority, setPriority] = useState(0)
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false)
  const [selectedPermissions, setSelectedPermissions] = useState<Set<string>>(
    new Set(),
  )
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())

  // Validation
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  // Group available permissions by resource_type
  const groupedPermissions = useMemo(
    () => groupPermissionsByResource(adminSettings?.permissions || []),
    [adminSettings?.permissions],
  )

  // Expand all groups by default when permissions load
  useEffect(() => {
    if (adminSettings?.permissions) {
      const groups = new Set(
        adminSettings.permissions.map((p) => p.resource_type),
      )
      setExpandedGroups(groups)
    }
  }, [adminSettings?.permissions])

  // Populate form when editing
  useEffect(() => {
    if (existingRole) {
      setName(existingRole.name)
      setSlug(existingRole.slug)
      setDescription(existingRole.description || '')
      setPriority(existingRole.priority)
      setSlugManuallyEdited(true)
      setSelectedPermissions(
        new Set(existingRole.permissions?.map((p) => p.name) || []),
      )
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
    onSave(roleData, Array.from(selectedPermissions))
  }

  const handleFieldChange = (field: string) => {
    setTouched({ ...touched, [field]: true })
    if (validationErrors[field]) {
      const newErrors = { ...validationErrors }
      delete newErrors[field]
      setValidationErrors(newErrors)
    }
  }

  const togglePermission = (permName: string) => {
    const next = new Set(selectedPermissions)
    if (next.has(permName)) {
      next.delete(permName)
    } else {
      next.add(permName)
    }
    setSelectedPermissions(next)
  }

  const toggleGroup = (resource: string) => {
    const next = new Set(expandedGroups)
    if (next.has(resource)) {
      next.delete(resource)
    } else {
      next.add(resource)
    }
    setExpandedGroups(next)
  }

  const toggleAllInGroup = (resource: string) => {
    const groupPerms = groupedPermissions[resource]?.map((p) => p.name) || []
    const allSelected = groupPerms.every((p) => selectedPermissions.has(p))

    const next = new Set(selectedPermissions)
    if (allSelected) {
      for (const p of groupPerms) {
        next.delete(p)
      }
    } else {
      for (const p of groupPerms) {
        next.add(p)
      }
    }
    setSelectedPermissions(next)
  }

  if (isEditing && roleLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading role...
        </div>
      </div>
    )
  }

  if (isEditing && roleError) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${
          isDarkMode
            ? 'border-red-700 bg-red-900/20 text-red-400'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load role</div>
          <div className="mt-1 text-sm">
            {roleError instanceof Error
              ? roleError.message
              : 'An error occurred'}
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
          <h2
            className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {isEditing ? 'Edit Role' : 'Create New Role'}
          </h2>
          <p
            className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {isEditing
              ? 'Update role information and permissions'
              : 'Create a new role and define its permissions'}
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
          {!isSystemRole && (
            <Button
              onClick={handleSave}
              disabled={
                isLoading ||
                (!isEditing && (adminSettingsLoading || !!adminSettingsError))
              }
              className="bg-[#2A4DD0] text-white hover:bg-blue-700"
            >
              <Save className="mr-2 h-4 w-4" />
              {isLoading
                ? 'Saving...'
                : isEditing
                  ? 'Save Changes'
                  : 'Create Role'}
            </Button>
          )}
        </div>
      </div>

      {/* System Role Warning */}
      {isSystemRole && (
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-amber-700 bg-amber-900/20'
              : 'border-amber-200 bg-amber-50'
          }`}
        >
          <div className="flex items-start gap-3">
            <AlertTriangle
              className={`h-5 w-5 flex-shrink-0 ${
                isDarkMode ? 'text-amber-400' : 'text-amber-600'
              }`}
            />
            <div>
              <div
                className={`font-medium ${isDarkMode ? 'text-amber-400' : 'text-amber-800'}`}
              >
                System Role
              </div>
              <div
                className={`mt-1 text-sm ${isDarkMode ? 'text-amber-300' : 'text-amber-700'}`}
              >
                This is a system role and cannot be modified. System roles are
                managed automatically.
              </div>
            </div>
          </div>
        </div>
      )}

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
                Failed to save role
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

      {/* Role Details */}
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
          Role Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Name */}
          <div className="col-span-2">
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
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
              className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                isSystemRole ? 'cursor-not-allowed opacity-60' : ''
              }`}
            />
            {touched.name && validationErrors.name && (
              <p className="mt-1 text-sm text-red-600">
                {validationErrors.name}
              </p>
            )}
          </div>

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
                const err = validateSlug(slug)
                if (err) setValidationErrors({ ...validationErrors, slug: err })
              }}
              disabled={isLoading || isSystemRole}
              placeholder="e.g. project-manager"
              className={`font-mono ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                isSystemRole ? 'cursor-not-allowed opacity-60' : ''
              }`}
            />
            {!isEditing && !slugManuallyEdited && name && (
              <p
                className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
              >
                Auto-generated from name
              </p>
            )}
            {touched.slug && validationErrors.slug && (
              <p className="mt-1 text-sm text-red-600">
                {validationErrors.slug}
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
              disabled={isLoading || isSystemRole}
              placeholder="Brief description of this role's purpose and scope"
              rows={3}
              className={`w-full resize-none rounded-md border px-3 py-2 text-sm ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700 text-white placeholder-gray-400'
                  : 'border-gray-300 bg-white text-gray-900 placeholder-gray-500'
              } ${isSystemRole ? 'cursor-not-allowed opacity-60' : ''}`}
            />
          </div>

          {/* Priority */}
          <div className="col-span-2 sm:col-span-1">
            <label
              className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
            >
              Priority
            </label>
            <Input
              type="number"
              value={priority}
              onChange={(e) => setPriority(parseInt(e.target.value, 10) || 0)}
              disabled={isLoading || isSystemRole}
              placeholder="0"
              className={`${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''} ${
                isSystemRole ? 'cursor-not-allowed opacity-60' : ''
              }`}
            />
            <p
              className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
            >
              Higher priority roles take precedence. System roles use 100-1000.
            </p>
          </div>
        </div>
      </div>

      {/* Permissions Selection */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3
            className={`font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Permissions
          </h3>
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {selectedPermissions.size} selected
          </div>
        </div>

        <div
          className={`mb-4 flex items-start gap-2 rounded-lg p-3 ${
            isDarkMode
              ? 'bg-blue-900/20 text-blue-400'
              : 'bg-blue-50 text-blue-700'
          }`}
        >
          <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
          <div className="text-xs">
            Select the permissions this role should have. Permissions are
            grouped by resource type for easier management.
            {isEditing && existingRole && (
              <> Changes will affect all users and groups with this role.</>
            )}
          </div>
        </div>

        <div className="space-y-3">
          {adminSettingsLoading && (
            <div
              className={`py-6 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              Loading permissions...
            </div>
          )}
          {adminSettingsError && (
            <div
              className={`py-6 text-center ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
            >
              Failed to load permissions. Please retry.
            </div>
          )}
          {Object.entries(groupedPermissions)
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([resource, perms]) => {
              const isExpanded = expandedGroups.has(resource)
              const selectedCount = perms.filter((p) =>
                selectedPermissions.has(p.name),
              ).length
              const allSelected = selectedCount === perms.length
              const someSelected =
                selectedCount > 0 && selectedCount < perms.length

              return (
                <div
                  key={resource}
                  className={`rounded-lg border ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-700'
                      : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  {/* Group Header */}
                  <div className="flex items-center gap-3 p-3">
                    <button
                      type="button"
                      onClick={() => toggleGroup(resource)}
                      aria-label={
                        isExpanded
                          ? 'Collapse permissions group'
                          : 'Expand permissions group'
                      }
                      aria-expanded={isExpanded}
                      className={`rounded p-0.5 ${
                        isDarkMode ? 'hover:bg-gray-700' : 'hover:bg-gray-200'
                      }`}
                    >
                      {isExpanded ? (
                        <ChevronDown
                          className={`h-4 w-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        />
                      ) : (
                        <ChevronRight
                          className={`h-4 w-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                        />
                      )}
                    </button>

                    <div className="flex flex-1 items-center gap-2">
                      <Checkbox
                        id={`group-${resource}`}
                        checked={
                          allSelected
                            ? true
                            : someSelected
                              ? 'indeterminate'
                              : false
                        }
                        disabled={isSystemRole}
                        onCheckedChange={() => toggleAllInGroup(resource)}
                      />
                      <label
                        htmlFor={`group-${resource}`}
                        className={`flex-1 cursor-pointer select-none ${
                          isDarkMode ? 'text-white' : 'text-gray-900'
                        }`}
                      >
                        {resourceLabel(resource)}
                      </label>
                      <span
                        className={`rounded-full px-2 py-0.5 text-xs ${
                          selectedCount > 0
                            ? isDarkMode
                              ? 'bg-blue-900/40 text-blue-400'
                              : 'bg-blue-100 text-blue-700'
                            : isDarkMode
                              ? 'bg-gray-700 text-gray-400'
                              : 'bg-gray-200 text-gray-600'
                        }`}
                      >
                        {selectedCount}/{perms.length}
                      </span>
                    </div>
                  </div>

                  {/* Group Permissions */}
                  {isExpanded && (
                    <div
                      className={`space-y-2 border-t px-3 pb-3 ${
                        isDarkMode ? 'border-gray-600' : 'border-gray-200'
                      }`}
                    >
                      {perms
                        .sort((a, b) => a.action.localeCompare(b.action))
                        .map((perm) => (
                          <div
                            key={perm.name}
                            className={`rounded flex items-start gap-3 p-2.5 ${
                              isDarkMode
                                ? 'hover:bg-gray-700'
                                : 'hover:bg-white'
                            }`}
                          >
                            <Checkbox
                              id={perm.name}
                              checked={selectedPermissions.has(perm.name)}
                              disabled={isSystemRole}
                              onCheckedChange={() =>
                                togglePermission(perm.name)
                              }
                              className="mt-0.5"
                            />
                            <label
                              htmlFor={perm.name}
                              className="flex-1 cursor-pointer select-none"
                            >
                              <div
                                className={`text-sm ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                              >
                                <code
                                  className={`rounded px-1.5 py-0.5 text-xs ${
                                    isDarkMode
                                      ? 'bg-gray-700 text-blue-400'
                                      : 'bg-gray-200 text-[#2A4DD0]'
                                  }`}
                                >
                                  {perm.action}
                                </code>
                              </div>
                              <div
                                className={`mt-0.5 text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                              >
                                {perm.description || perm.name}
                              </div>
                            </label>
                          </div>
                        ))}
                    </div>
                  )}
                </div>
              )
            })}

          {!adminSettingsLoading &&
            !adminSettingsError &&
            (!adminSettings?.permissions ||
              adminSettings.permissions.length === 0) && (
              <div
                className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
              >
                <div>No permissions available</div>
                <div className="mt-1 text-sm">
                  Permissions are configured in the backend
                </div>
              </div>
            )}
        </div>
      </div>
    </div>
  )
}
