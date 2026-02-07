import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertTriangle, Eye, EyeOff, Check, X as XIcon, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { Gravatar } from '../../ui/gravatar'
import { getRoles } from '@/api/endpoints'
import type { AdminUser, AdminUserCreate } from '@/types'

interface UserFormProps {
  user: AdminUser | null
  onSave: (user: AdminUserCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
}

export function UserForm({ user, onSave, onCancel, isDarkMode, isLoading = false, error }: UserFormProps) {
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
  const [isServiceAccount, setIsServiceAccount] = useState(user?.is_service_account ?? false)

  // Roles - store slugs
  const [selectedRoleSlugs, setSelectedRoleSlugs] = useState<string[]>(
    user?.roles.map(r => r.slug) || []
  )

  // Fetch available roles
  const { data: availableRoles = [], isLoading: rolesLoading } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles
  })

  // Validation state
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  // Password strength
  const getPasswordStrength = (pwd: string): { score: number; label: string; color: string } => {
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

    setValidationErrors(errors)
    setTouched({
      email: true,
      display_name: true,
      password: true,
      confirmPassword: true
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
      is_service_account: isServiceAccount
    }

    // Only include password if changing it or creating new user
    if (changePassword || !isEditing) {
      userData.password = password
    }

    // Note: Groups and roles might need to be set via separate API calls
    // depending on the backend implementation. For now, we're not including them
    // in the AdminUserCreate payload as they're not in the type definition.

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
          <h2 className={`text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEditing ? 'Edit User' : 'Create New User'}
          </h2>
          <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {isEditing ? `Editing ${user?.display_name}` : 'Add a new user account to the system'}
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
            {isLoading ? 'Saving...' : (isEditing ? 'Save Changes' : 'Create User')}
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
                Failed to save user
              </div>
              <div className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}>
                {error?.response?.data?.detail || error?.message || 'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Section 1: Basic Information */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Basic Information
        </h3>

        <div className="grid grid-cols-2 gap-4">
          {/* Email */}
          <div className="col-span-2">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
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
              disabled={isEditing || isLoading}
              placeholder="john.doe@company.com"
              className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                isEditing ? 'opacity-60 cursor-not-allowed' : ''
              }`}
            />
            {isEditing && (
              <p className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                Email cannot be changed after creation
              </p>
            )}
            {touched.email && validationErrors.email && (
              <p className="text-sm text-red-600 mt-1">{validationErrors.email}</p>
            )}
          </div>

          {/* Display Name */}
          <div className="col-span-2">
            <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
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
                  setValidationErrors({ ...validationErrors, display_name: error })
                }
              }}
              disabled={isLoading}
              placeholder="John Doe"
              className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
            />
            {touched.display_name && validationErrors.display_name && (
              <p className="text-sm text-red-600 mt-1">{validationErrors.display_name}</p>
            )}
          </div>

          {/* Gravatar Preview */}
          {email && validateEmail(email) === '' && (
            <div className="col-span-2">
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Avatar (Gravatar)
              </label>
              <div className="flex items-center gap-3">
                <Gravatar
                  email={email}
                  size={64}
                  className="w-16 h-16 rounded-full border-2 border-gray-300 dark:border-gray-600"
                />
                <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                  Avatar will be loaded from <a href="https://gravatar.com" target="_blank" rel="noopener noreferrer" className="text-blue-500 hover:underline">Gravatar</a> based on email address
                </p>
              </div>
            </div>
          )}

          {/* Password Section */}
          {isEditing && (
            <div className="col-span-2">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={changePassword}
                  onChange={(e) => setChangePassword(e.target.checked)}
                  disabled={isLoading}
                  className="rounded"
                />
                <span className={isDarkMode ? 'text-gray-300' : 'text-gray-700'}>
                  Change Password
                </span>
              </label>
            </div>
          )}

          {(changePassword || !isEditing) && (
            <>
              <div className="col-span-2">
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
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
                        setValidationErrors({ ...validationErrors, password: error })
                      }
                    }}
                    disabled={isLoading}
                    placeholder="Minimum 12 characters"
                    className={`pr-10 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword(!showPassword)}
                    disabled={isLoading}
                    className={`absolute right-3 top-1/2 -translate-y-1/2 ${
                      isDarkMode ? 'text-gray-400 hover:text-gray-200' : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                  </button>
                </div>
                {touched.password && validationErrors.password && (
                  <p className="text-sm text-red-600 mt-1">{validationErrors.password}</p>
                )}
                {password && !validationErrors.password && (
                  <div className="mt-2">
                    <div className="flex items-center gap-2 mb-1">
                      <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className={`h-full transition-all ${
                            passwordStrength.color === 'red' ? 'bg-red-500' :
                            passwordStrength.color === 'yellow' ? 'bg-yellow-500' :
                            'bg-green-500'
                          }`}
                          style={{ width: `${(passwordStrength.score / 6) * 100}%` }}
                        />
                      </div>
                      <span className={`text-xs ${
                        passwordStrength.color === 'red' ? 'text-red-500' :
                        passwordStrength.color === 'yellow' ? 'text-yellow-500' :
                        'text-green-500'
                      }`}>
                        {passwordStrength.label}
                      </span>
                    </div>
                    <ul className={`text-xs space-y-0.5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                      <li className={`flex items-center gap-1 ${password.length >= 12 ? 'text-green-600 dark:text-green-400' : ''}`}>
                        {password.length >= 12 ? <Check className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
                        At least 12 characters
                      </li>
                      <li className={`flex items-center gap-1 ${/[A-Z]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}>
                        {/[A-Z]/.test(password) ? <Check className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
                        Uppercase letter
                      </li>
                      <li className={`flex items-center gap-1 ${/[a-z]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}>
                        {/[a-z]/.test(password) ? <Check className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
                        Lowercase letter
                      </li>
                      <li className={`flex items-center gap-1 ${/[0-9]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}>
                        {/[0-9]/.test(password) ? <Check className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
                        Number
                      </li>
                      <li className={`flex items-center gap-1 ${/[^a-zA-Z0-9]/.test(password) ? 'text-green-600 dark:text-green-400' : ''}`}>
                        {/[^a-zA-Z0-9]/.test(password) ? <Check className="w-3 h-3" /> : <XIcon className="w-3 h-3" />}
                        Special character
                      </li>
                    </ul>
                  </div>
                )}
              </div>

              <div className="col-span-2">
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
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
                      setValidationErrors({ ...validationErrors, confirmPassword: error })
                    }
                  }}
                  disabled={isLoading}
                  placeholder="Re-enter password"
                  className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
                />
                {touched.confirmPassword && validationErrors.confirmPassword && (
                  <p className="text-sm text-red-600 mt-1">{validationErrors.confirmPassword}</p>
                )}
              </div>
            </>
          )}
        </div>
      </div>

      {/* Section 2: Account Type */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Account Type & Status
        </h3>

        <div className="space-y-4">
          <div>
            <label className={`block text-sm mb-2 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
              Account Type
            </label>
            <div className="space-y-2">
              <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${
                !isAdmin && !isServiceAccount
                  ? isDarkMode ? 'border-blue-700 bg-blue-900/20' : 'border-blue-300 bg-blue-50'
                  : isDarkMode ? 'border-gray-600' : 'border-gray-200'
              }`}>
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
                  <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>Regular User</div>
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    Standard user account with role-based permissions
                  </div>
                </div>
              </label>

              <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${
                isServiceAccount
                  ? isDarkMode ? 'border-purple-700 bg-purple-900/20' : 'border-purple-300 bg-purple-50'
                  : isDarkMode ? 'border-gray-600' : 'border-gray-200'
              }`}>
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
                  <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>Service Account</div>
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    Automated system account for API access
                  </div>
                </div>
              </label>

              <label className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer ${
                isAdmin
                  ? isDarkMode ? 'border-red-700 bg-red-900/20' : 'border-red-300 bg-red-50'
                  : isDarkMode ? 'border-gray-600' : 'border-gray-200'
              }`}>
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
                  <div className={`flex items-center gap-2 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                    Administrator
                    <AlertTriangle className="w-4 h-4 text-red-500" />
                  </div>
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    Super-user with full system access (bypasses all permission checks)
                  </div>
                </div>
              </label>
            </div>
          </div>

          <div>
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                disabled={isLoading}
                className="rounded"
              />
              <span className={isDarkMode ? 'text-gray-300' : 'text-gray-700'}>
                Account Active
              </span>
            </label>
            <p className={`text-sm mt-1 ml-6 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              Inactive accounts cannot authenticate
            </p>
          </div>
        </div>
      </div>

      {/* Section 3: Role Assignments */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Direct Role Assignments
        </h3>

        {rolesLoading ? (
          <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Loading roles...
          </p>
        ) : availableRoles.length === 0 ? (
          <p className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            No roles available
          </p>
        ) : (
          <div className="space-y-3">
            {availableRoles.map((role) => (
              <label key={role.slug} className="flex items-start gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={selectedRoleSlugs.includes(role.slug)}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedRoleSlugs([...selectedRoleSlugs, role.slug])
                    } else {
                      setSelectedRoleSlugs(selectedRoleSlugs.filter(s => s !== role.slug))
                    }
                  }}
                  disabled={isLoading}
                  className="rounded mt-0.5"
                />
                <div className="flex-1">
                  <span className={isDarkMode ? 'text-gray-300' : 'text-gray-700'}>
                    {role.name}
                  </span>
                  {role.description && (
                    <p className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
                      {role.description}
                    </p>
                  )}
                </div>
              </label>
            ))}
          </div>
        )}
        <p className={`text-xs mt-3 ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}>
          Note: Role assignments may need to be configured separately after user creation, depending on backend implementation.
        </p>
      </div>
    </div>
  )
}
