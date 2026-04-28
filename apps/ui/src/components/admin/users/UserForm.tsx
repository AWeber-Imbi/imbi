import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Eye,
  EyeOff,
  X as XIcon,
} from 'lucide-react'

import { getRoles } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { FormField } from '@/components/ui/form-field'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useFormScaffold } from '@/hooks/useFormScaffold'
import type { AdminUser, AdminUserCreate } from '@/types'

import { Card, CardContent } from '../../ui/card'
import { Gravatar } from '../../ui/gravatar'
import { Input } from '../../ui/input'

interface UserFormProps {
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onSave: (user: AdminUserCreate) => void
  user: AdminUser | null
}

export function UserForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  user,
}: UserFormProps) {
  const isEditing = !!user

  // Basic info
  const [email, setEmail] = useState(user?.email || '')
  const [displayName, setDisplayName] = useState(user?.display_name || '')

  // Password
  const [changePassword, setChangePassword] = useState(!isEditing)
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  // Account type
  const [isActive, setIsActive] = useState(user?.is_active ?? true)
  const [isAdmin, setIsAdmin] = useState(user?.is_admin ?? false)
  const [isServiceAccount, setIsServiceAccount] = useState(
    user?.is_service_account ?? false,
  )

  // Organization membership (for creation only)
  const { organizations } = useOrganization()
  const [organizationSlug, setOrganizationSlug] = useState(
    organizations.length === 1 ? organizations[0].slug : '',
  )
  const [roleSlug, setRoleSlug] = useState('')

  // Fetch available roles
  const { data: availableRoles = [], isLoading: rolesLoading } = useQuery({
    queryFn: ({ signal }) => getRoles(signal),
    queryKey: ['roles'],
  })

  // Validation state
  const {
    handleFieldChange,
    setTouched,
    setValidationErrors,
    touched,
    validationErrors,
  } = useFormScaffold()

  // Password strength
  const getPasswordStrength = (
    pwd: string,
  ): { color: string; label: string; score: number } => {
    if (!pwd) return { color: '', label: '', score: 0 }

    let score = 0
    if (pwd.length >= 12) score++
    if (pwd.length >= 16) score++
    if (/[a-z]/.test(pwd)) score++
    if (/[A-Z]/.test(pwd)) score++
    if (/[0-9]/.test(pwd)) score++
    if (/[^a-zA-Z0-9]/.test(pwd)) score++

    if (score <= 2) return { color: 'red', label: 'Weak', score }
    if (score <= 4) return { color: 'yellow', label: 'Medium', score }
    return { color: 'green', label: 'Strong', score }
  }

  const passwordStrength = getPasswordStrength(password)

  // Validation functions
  const validateEmail = (value: string): string => {
    if (!value.trim()) return 'Email is required'
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return 'Invalid email format'
    return ''
  }

  const validateDisplayName = (value: string): string => {
    if (!value.trim()) return 'Display name is required'
    return ''
  }

  const validatePassword = (value: string): string => {
    if (changePassword || !isEditing) {
      if (!value) return 'Password is required'
      if (value.length < 12) return 'Password must be at least 12 characters'
      if (passwordStrength.score < 3) return 'Password is too weak'
    }
    return ''
  }

  const validateConfirmPassword = (value: string): string => {
    if ((changePassword || !isEditing) && value !== password) {
      return 'Passwords do not match'
    }
    return ''
  }

  // Validate all fields
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}

    const emailError = validateEmail(email)
    if (emailError) errors.email = emailError

    const displayNameError = validateDisplayName(displayName)
    if (displayNameError) errors.display_name = displayNameError

    if (changePassword || !isEditing) {
      const passwordError = validatePassword(password)
      if (passwordError) errors.password = passwordError

      const confirmError = validateConfirmPassword(confirmPassword)
      if (confirmError) errors.confirmPassword = confirmError
    }

    if (!isEditing) {
      if (!organizationSlug)
        errors.organization_slug = 'Organization is required'
      if (!roleSlug) errors.role_slug = 'Role is required'
    }

    setValidationErrors(errors)
    setTouched({
      confirmPassword: true,
      display_name: true,
      email: true,
      organization_slug: true,
      password: true,
      role_slug: true,
    })

    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (!validateForm()) {
      return
    }

    const userData: AdminUserCreate = {
      display_name: displayName.trim(),
      email: email.trim(),
      is_active: isActive,
      is_admin: isAdmin,
      is_service_account: isServiceAccount,
      organization_slug: organizationSlug,
      role_slug: roleSlug,
    }

    // Only include password if changing it or creating new user
    if (changePassword || !isEditing) {
      userData.password = password
    }

    onSave(userData)
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <FormHeader
        createLabel="Create User"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing
            ? `Editing ${user?.display_name}`
            : 'Add a new user account to the system'
        }
        title={isEditing ? 'Edit User' : 'Create New User'}
      />

      {/* API Error Display */}
      {error && (
        <div className="rounded-lg border border-danger bg-danger p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-danger" />
            <div>
              <div className="font-medium text-danger">Failed to save user</div>
              <div className="mt-1 text-sm text-danger">
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Section 1: Basic Information */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-2 gap-4">
            {/* Email */}
            {!isEditing && (
              <div className="col-span-2">
                <FormField
                  error={validationErrors.email}
                  label="Email"
                  required
                  touched={touched.email}
                >
                  <Input
                    className=""
                    disabled={isLoading}
                    onBlur={() => {
                      setTouched({ ...touched, email: true })
                      const error = validateEmail(email)
                      if (error) {
                        setValidationErrors({
                          ...validationErrors,
                          email: error,
                        })
                      }
                    }}
                    onChange={(e) => {
                      setEmail(e.target.value)
                      handleFieldChange('email')
                    }}
                    placeholder="john.doe@company.com"
                    type="email"
                    value={email}
                  />
                </FormField>
              </div>
            )}

            {/* Display Name */}
            <div className="col-span-2">
              <FormField
                error={validationErrors.display_name}
                label="Display Name"
                required
                touched={touched.display_name}
              >
                <Input
                  className=""
                  disabled={isLoading}
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
                  onChange={(e) => {
                    setDisplayName(e.target.value)
                    handleFieldChange('display_name')
                  }}
                  placeholder="John Doe"
                  value={displayName}
                />
              </FormField>
            </div>

            {/* Gravatar Preview */}
            {email && validateEmail(email) === '' && (
              <div className="col-span-2">
                <FormField label="Avatar (Gravatar)">
                  <div className="flex items-center gap-3">
                    <Gravatar
                      className="h-16 w-16 rounded-full border-2 border-gray-300 dark:border-gray-600"
                      email={email}
                      size={64}
                    />
                    <p className="text-sm text-secondary">
                      Avatar will be loaded from{' '}
                      <a
                        className="text-blue-500 hover:underline"
                        href="https://gravatar.com"
                        rel="noopener noreferrer"
                        target="_blank"
                      >
                        Gravatar
                      </a>{' '}
                      based on email address
                    </p>
                  </div>
                </FormField>
              </div>
            )}

            {/* Password Section */}
            {isEditing && (
              <div className="col-span-2">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    checked={changePassword}
                    className="rounded"
                    disabled={isLoading}
                    onChange={(e) => setChangePassword(e.target.checked)}
                    type="checkbox"
                  />
                  <span className="text-secondary">Change Password</span>
                </label>
              </div>
            )}

            {(changePassword || !isEditing) && (
              <>
                <div className="col-span-2">
                  <FormField
                    error={validationErrors.password}
                    label="Password"
                    required
                    touched={touched.password}
                  >
                    <div className="relative">
                      <Input
                        className="pr-10"
                        disabled={isLoading}
                        onBlur={() => {
                          setTouched({ ...touched, password: true })
                          const error = validatePassword(password)
                          if (error) {
                            setValidationErrors({
                              ...validationErrors,
                              password: error,
                            })
                          }
                        }}
                        onChange={(e) => {
                          setPassword(e.target.value)
                          handleFieldChange('password')
                        }}
                        placeholder="Minimum 12 characters"
                        type={showPassword ? 'text' : 'password'}
                        value={password}
                      />
                      <button
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-tertiary hover:text-secondary"
                        disabled={isLoading}
                        onClick={() => setShowPassword(!showPassword)}
                        type="button"
                      >
                        {showPassword ? (
                          <EyeOff className="h-4 w-4" />
                        ) : (
                          <Eye className="h-4 w-4" />
                        )}
                      </button>
                    </div>
                  </FormField>
                  {password && !validationErrors.password && (
                    <div className="mt-2">
                      <div className="mb-1 flex items-center gap-2">
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
                          <div
                            className={`h-full transition-all ${
                              passwordStrength.color === 'red'
                                ? 'bg-red-500'
                                : passwordStrength.color === 'yellow'
                                  ? 'bg-yellow-500'
                                  : 'bg-green-500'
                            }`}
                            style={{
                              width: `${(passwordStrength.score / 6) * 100}%`,
                            }}
                          />
                        </div>
                        <span
                          className={`text-xs ${
                            passwordStrength.color === 'red'
                              ? 'text-red-500'
                              : passwordStrength.color === 'yellow'
                                ? 'text-yellow-500'
                                : 'text-green-500'
                          }`}
                        >
                          {passwordStrength.label}
                        </span>
                      </div>
                      <ul className="space-y-0.5 text-xs text-secondary">
                        <li
                          className={`flex items-center gap-1 ${password.length >= 12 ? 'text-green-600 dark:text-green-400' : ''}`}
                        >
                          {password.length >= 12 ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <XIcon className="h-3 w-3" />
                          )}
                          At least 12 characters
                        </li>
                        <li
                          className={`flex items-center gap-1 ${/[A-Z]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}
                        >
                          {/[A-Z]/.test(password) ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <XIcon className="h-3 w-3" />
                          )}
                          Uppercase letter
                        </li>
                        <li
                          className={`flex items-center gap-1 ${/[a-z]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}
                        >
                          {/[a-z]/.test(password) ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <XIcon className="h-3 w-3" />
                          )}
                          Lowercase letter
                        </li>
                        <li
                          className={`flex items-center gap-1 ${/[0-9]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}
                        >
                          {/[0-9]/.test(password) ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <XIcon className="h-3 w-3" />
                          )}
                          Number
                        </li>
                        <li
                          className={`flex items-center gap-1 ${/[^a-zA-Z0-9]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}
                        >
                          {/[^a-zA-Z0-9]/.test(password) ? (
                            <Check className="h-3 w-3" />
                          ) : (
                            <XIcon className="h-3 w-3" />
                          )}
                          Special character
                        </li>
                      </ul>
                    </div>
                  )}
                </div>

                <div className="col-span-2">
                  <FormField
                    error={validationErrors.confirmPassword}
                    label="Confirm Password"
                    required
                    touched={touched.confirmPassword}
                  >
                    <Input
                      className=""
                      disabled={isLoading}
                      onBlur={() => {
                        setTouched({ ...touched, confirmPassword: true })
                        const error = validateConfirmPassword(confirmPassword)
                        if (error) {
                          setValidationErrors({
                            ...validationErrors,
                            confirmPassword: error,
                          })
                        }
                      }}
                      onChange={(e) => {
                        setConfirmPassword(e.target.value)
                        handleFieldChange('confirmPassword')
                      }}
                      placeholder="Re-enter password"
                      type={showPassword ? 'text' : 'password'}
                      value={confirmPassword}
                    />
                  </FormField>
                </div>
              </>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Section 2: Account Type */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div>
            <label className="mb-2 block text-sm text-secondary">
              Account Type
            </label>
            <div className="space-y-2">
              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${
                  !isAdmin && !isServiceAccount
                    ? 'border-info bg-info'
                    : 'border-secondary'
                }`}
              >
                <input
                  checked={!isAdmin && !isServiceAccount}
                  className="mt-0.5"
                  disabled={isLoading}
                  name="accountType"
                  onChange={() => {
                    setIsAdmin(false)
                    setIsServiceAccount(false)
                  }}
                  type="radio"
                />
                <div className="flex-1">
                  <div className="text-primary">Regular User</div>
                  <div className="text-sm text-secondary">
                    Standard user account with role-based permissions
                  </div>
                </div>
              </label>

              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${
                  isServiceAccount
                    ? 'border-purple-300 bg-purple-50 dark:border-purple-700 dark:bg-purple-900/20'
                    : 'border-secondary'
                }`}
              >
                <input
                  checked={isServiceAccount}
                  className="mt-0.5"
                  disabled={isLoading}
                  name="accountType"
                  onChange={() => {
                    setIsServiceAccount(true)
                    setIsAdmin(false)
                  }}
                  type="radio"
                />
                <div className="flex-1">
                  <div className="text-primary">Service Account</div>
                  <div className="text-sm text-secondary">
                    Automated system account for API access
                  </div>
                </div>
              </label>

              <label
                className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 ${
                  isAdmin ? 'border-danger bg-danger' : 'border-secondary'
                }`}
              >
                <input
                  checked={isAdmin}
                  className="mt-0.5"
                  disabled={isLoading}
                  name="accountType"
                  onChange={() => {
                    setIsAdmin(true)
                    setIsServiceAccount(false)
                  }}
                  type="radio"
                />
                <div className="flex-1">
                  <div className="flex items-center gap-2 text-primary">
                    Administrator
                    <AlertTriangle className="h-4 w-4 text-red-500" />
                  </div>
                  <div className="text-sm text-secondary">
                    Super-user with full system access (bypasses all permission
                    checks)
                  </div>
                </div>
              </label>
            </div>
          </div>

          <div>
            <label className="flex cursor-pointer items-center gap-2">
              <input
                checked={isActive}
                className="rounded"
                disabled={isLoading}
                onChange={(e) => setIsActive(e.target.checked)}
                type="checkbox"
              />
              <span className="text-secondary">Account Active</span>
            </label>
            <p className="ml-6 mt-1 text-sm text-secondary">
              Inactive accounts cannot authenticate
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Section 3: Organization Membership (creation only) */}
      {!isEditing && (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <p className="mb-4 text-sm text-secondary">
              Users must belong to at least one organization with a role to have
              any permissions.
            </p>

            <div className="grid grid-cols-2 gap-4">
              {/* Organization */}
              <FormField
                error={validationErrors.organization_slug}
                label="Organization"
                required
                touched={touched.organization_slug}
              >
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                  disabled={isLoading}
                  onChange={(e) => {
                    setOrganizationSlug(e.target.value)
                    handleFieldChange('organization_slug')
                  }}
                  value={organizationSlug}
                >
                  <option value="">Select an organization...</option>
                  {organizations.map((org) => (
                    <option key={org.slug} value={org.slug}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </FormField>

              {/* Role */}
              <FormField
                error={validationErrors.role_slug}
                label="Role"
                required
                touched={touched.role_slug}
              >
                {rolesLoading ? (
                  <p className="text-sm text-secondary">Loading roles...</p>
                ) : (
                  <select
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500"
                    disabled={isLoading}
                    onChange={(e) => {
                      setRoleSlug(e.target.value)
                      handleFieldChange('role_slug')
                    }}
                    value={roleSlug}
                  >
                    <option value="">Select a role...</option>
                    {availableRoles.map((role) => (
                      <option key={role.slug} value={role.slug}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                )}
              </FormField>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
