import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Save,
  X,
  AlertTriangle,
  Eye,
  EyeOff,
  Check,
  X as XIcon,
  AlertCircle,
} from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { Gravatar } from '../../ui/gravatar'
import { Card, CardContent } from '../../ui/card'
import { getRoles } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { AdminUser, AdminUserCreate } from '@/types'

interface UserFormProps {
  user: AdminUser | null
  onSave: (user: AdminUserCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: { response?: { data?: { detail?: string } }; message?: string } | null
}

export function UserForm({
  user,
  onSave,
  onCancel,
  isLoading = false,
  error,
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
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  // Validation state
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  // Password strength
  const getPasswordStrength = (
    pwd: string,
  ): { score: number; label: string; color: string } => {
    if (!pwd) return { score: 0, label: '', color: '' }

    let score = 0
    if (pwd.length >= 12) score++
    if (pwd.length >= 16) score++
    if (/[a-z]/.test(pwd)) score++
    if (/[A-Z]/.test(pwd)) score++
    if (/[0-9]/.test(pwd)) score++
    if (/[^a-zA-Z0-9]/.test(pwd)) score++

    if (score <= 2) return { score, label: 'Weak', color: 'red' }
    if (score <= 4) return { score, label: 'Medium', color: 'yellow' }
    return { score, label: 'Strong', color: 'green' }
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
      email: true,
      display_name: true,
      password: true,
      confirmPassword: true,
      organization_slug: true,
      role_slug: true,
    })

    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (!validateForm()) {
      return
    }

    const userData: AdminUserCreate = {
      email: email.trim(),
      display_name: displayName.trim(),
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

  const handleFieldChange = (field: string) => {
    setTouched({ ...touched, [field]: true })

    // Clear validation error for this field
    if (validationErrors[field]) {
      const newErrors = { ...validationErrors }
      delete newErrors[field]
      setValidationErrors(newErrors)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={'text-base font-medium text-primary'}>
            {isEditing ? 'Edit User' : 'Create New User'}
          </h2>
          <p className={'mt-1 text-secondary'}>
            {isEditing
              ? `Editing ${user?.display_name}`
              : 'Add a new user account to the system'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoading}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create User'}
          </Button>
        </div>
      </div>

      {/* API Error Display */}
      {error && (
        <div className={`rounded-lg border p-4 ${'border-danger bg-danger'}`}>
          <div className="flex items-start gap-3">
            <AlertCircle className={`h-5 w-5 flex-shrink-0 ${'text-danger'}`} />
            <div>
              <div className={'font-medium text-danger'}>
                Failed to save user
              </div>
              <div className={'mt-1 text-sm text-danger'}>
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
                <label className={'mb-1.5 block text-sm text-secondary'}>
                  Email <span className="text-red-500">*</span>
                </label>
                <Input
                  type="email"
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    handleFieldChange('email')
                  }}
                  onBlur={() => {
                    setTouched({ ...touched, email: true })
                    const error = validateEmail(email)
                    if (error) {
                      setValidationErrors({ ...validationErrors, email: error })
                    }
                  }}
                  disabled={isLoading}
                  placeholder="john.doe@company.com"
                  className={''}
                />
                {touched.email && validationErrors.email && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.email}
                  </p>
                )}
              </div>
            )}

            {/* Display Name */}
            <div className="col-span-2">
              <label className={'mb-1.5 block text-sm text-secondary'}>
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
                placeholder="John Doe"
                className={''}
              />
              {touched.display_name && validationErrors.display_name && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.display_name}
                </p>
              )}
            </div>

            {/* Gravatar Preview */}
            {email && validateEmail(email) === '' && (
              <div className="col-span-2">
                <label className={'mb-1.5 block text-sm text-secondary'}>
                  Avatar (Gravatar)
                </label>
                <div className="flex items-center gap-3">
                  <Gravatar
                    email={email}
                    size={64}
                    className="h-16 w-16 rounded-full border-2 border-gray-300 dark:border-gray-600"
                  />
                  <p className={'text-sm text-secondary'}>
                    Avatar will be loaded from{' '}
                    <a
                      href="https://gravatar.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-500 hover:underline"
                    >
                      Gravatar
                    </a>{' '}
                    based on email address
                  </p>
                </div>
              </div>
            )}

            {/* Password Section */}
            {isEditing && (
              <div className="col-span-2">
                <label className="flex cursor-pointer items-center gap-2">
                  <input
                    type="checkbox"
                    checked={changePassword}
                    onChange={(e) => setChangePassword(e.target.checked)}
                    disabled={isLoading}
                    className="rounded"
                  />
                  <span className={'text-secondary'}>Change Password</span>
                </label>
              </div>
            )}

            {(changePassword || !isEditing) && (
              <>
                <div className="col-span-2">
                  <label className={'mb-1.5 block text-sm text-secondary'}>
                    Password <span className="text-red-500">*</span>
                  </label>
                  <div className="relative">
                    <Input
                      type={showPassword ? 'text' : 'password'}
                      value={password}
                      onChange={(e) => {
                        setPassword(e.target.value)
                        handleFieldChange('password')
                      }}
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
                      disabled={isLoading}
                      placeholder="Minimum 12 characters"
                      className={'pr-10'}
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(!showPassword)}
                      disabled={isLoading}
                      className={`absolute right-3 top-1/2 -translate-y-1/2 ${'text-tertiary hover:text-secondary'}`}
                    >
                      {showPassword ? (
                        <EyeOff className="h-4 w-4" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                    </button>
                  </div>
                  {touched.password && validationErrors.password && (
                    <p className="mt-1 text-sm text-red-600">
                      {validationErrors.password}
                    </p>
                  )}
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
                      <ul className={'space-y-0.5 text-xs text-secondary'}>
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
                  <label className={'mb-1.5 block text-sm text-secondary'}>
                    Confirm Password <span className="text-red-500">*</span>
                  </label>
                  <Input
                    type={showPassword ? 'text' : 'password'}
                    value={confirmPassword}
                    onChange={(e) => {
                      setConfirmPassword(e.target.value)
                      handleFieldChange('confirmPassword')
                    }}
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
                    disabled={isLoading}
                    placeholder="Re-enter password"
                    className={''}
                  />
                  {touched.confirmPassword &&
                    validationErrors.confirmPassword && (
                      <p className="mt-1 text-sm text-red-600">
                        {validationErrors.confirmPassword}
                      </p>
                    )}
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
            <label className={'mb-2 block text-sm text-secondary'}>
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
                  type="radio"
                  name="accountType"
                  checked={!isAdmin && !isServiceAccount}
                  onChange={() => {
                    setIsAdmin(false)
                    setIsServiceAccount(false)
                  }}
                  disabled={isLoading}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className={'text-primary'}>Regular User</div>
                  <div className={'text-sm text-secondary'}>
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
                  type="radio"
                  name="accountType"
                  checked={isServiceAccount}
                  onChange={() => {
                    setIsServiceAccount(true)
                    setIsAdmin(false)
                  }}
                  disabled={isLoading}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className={'text-primary'}>Service Account</div>
                  <div className={'text-sm text-secondary'}>
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
                  type="radio"
                  name="accountType"
                  checked={isAdmin}
                  onChange={() => {
                    setIsAdmin(true)
                    setIsServiceAccount(false)
                  }}
                  disabled={isLoading}
                  className="mt-0.5"
                />
                <div className="flex-1">
                  <div className={'flex items-center gap-2 text-primary'}>
                    Administrator
                    <AlertTriangle className="h-4 w-4 text-red-500" />
                  </div>
                  <div className={'text-sm text-secondary'}>
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
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                disabled={isLoading}
                className="rounded"
              />
              <span className={'text-secondary'}>Account Active</span>
            </label>
            <p className={'ml-6 mt-1 text-sm text-secondary'}>
              Inactive accounts cannot authenticate
            </p>
          </div>
        </CardContent>
      </Card>

      {/* Section 3: Organization Membership (creation only) */}
      {!isEditing && (
        <Card>
          <CardContent className="space-y-4 pt-6">
            <p className={'mb-4 text-sm text-secondary'}>
              Users must belong to at least one organization with a role to have
              any permissions.
            </p>

            <div className="grid grid-cols-2 gap-4">
              {/* Organization */}
              <div>
                <label className={'mb-1.5 block text-sm text-secondary'}>
                  Organization <span className="text-red-500">*</span>
                </label>
                <select
                  value={organizationSlug}
                  onChange={(e) => {
                    setOrganizationSlug(e.target.value)
                    handleFieldChange('organization_slug')
                  }}
                  disabled={isLoading}
                  className={`w-full rounded-md border px-3 py-2 text-sm ${'border-input bg-background text-foreground'} focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500`}
                >
                  <option value="">Select an organization...</option>
                  {organizations.map((org) => (
                    <option key={org.slug} value={org.slug}>
                      {org.name}
                    </option>
                  ))}
                </select>
                {touched.organization_slug &&
                  validationErrors.organization_slug && (
                    <p className="mt-1 text-sm text-red-600">
                      {validationErrors.organization_slug}
                    </p>
                  )}
              </div>

              {/* Role */}
              <div>
                <label className={'mb-1.5 block text-sm text-secondary'}>
                  Role <span className="text-red-500">*</span>
                </label>
                {rolesLoading ? (
                  <p className={'text-sm text-secondary'}>Loading roles...</p>
                ) : (
                  <select
                    value={roleSlug}
                    onChange={(e) => {
                      setRoleSlug(e.target.value)
                      handleFieldChange('role_slug')
                    }}
                    disabled={isLoading}
                    className={`w-full rounded-md border px-3 py-2 text-sm ${'border-input bg-background text-foreground'} focus:border-transparent focus:outline-none focus:ring-2 focus:ring-blue-500`}
                  >
                    <option value="">Select a role...</option>
                    {availableRoles.map((role) => (
                      <option key={role.slug} value={role.slug}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                )}
                {touched.role_slug && validationErrors.role_slug && (
                  <p className="mt-1 text-sm text-red-600">
                    {validationErrors.role_slug}
                  </p>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
