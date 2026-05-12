import { useEffect, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
  Check,
  Copy,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  LogOut,
  RefreshCw,
  Save,
  Shield,
  ShieldAlert,
  Trash2,
  User,
  X as XIcon,
} from 'lucide-react'

import { getLocalAuthConfig, getRoles } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FormField } from '@/components/ui/form-field'
import { Switch } from '@/components/ui/switch'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useFormScaffold } from '@/hooks/useFormScaffold'
import { cn } from '@/lib/utils'
import type { AdminUser, AdminUserCreate } from '@/types'

import { Gravatar } from '../../ui/gravatar'
import { Input } from '../../ui/input'

interface FormSectionProps {
  children: React.ReactNode
  description: string
  label: string
}

interface ResetPasswordModalProps {
  email: string
  isLoading: boolean
  onClose: () => void
  onConfirm: (password: string) => void
  open: boolean
}

interface ToggleRowProps {
  description: string
  disabled?: boolean
  id: string
  label: string
  onChange: (value: boolean) => void
  value: boolean
}

interface UserFormProps {
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isDeleting?: boolean
  isLoading?: boolean
  onCancel: () => void
  onDelete?: (user: AdminUser) => void
  onSave: (user: AdminUserCreate) => void
  user: AdminUser | null
}

export function UserForm({
  error,
  isDeleting = false,
  isLoading = false,
  onCancel,
  onDelete,
  onSave,
  user,
}: UserFormProps) {
  const isEditing = !!user

  const [email, setEmail] = useState(user?.email || '')
  const [displayName, setDisplayName] = useState(user?.display_name || '')

  const [changePassword, setChangePassword] = useState(!isEditing)
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  const [isActive, setIsActive] = useState(user?.is_active ?? true)
  const [isAdmin, setIsAdmin] = useState(user?.is_admin ?? false)
  const [emailNotifications, setEmailNotifications] = useState(
    user?.email_notifications ?? true,
  )

  const { organizations } = useOrganization()
  const [organizationSlug, setOrganizationSlug] = useState(
    organizations.length === 1 ? organizations[0].slug : '',
  )
  const [roleSlug, setRoleSlug] = useState('')

  const [memberships, setMemberships] = useState<
    { organization_slug: string; role: string }[]
  >(
    (user?.organizations ?? []).map((m) => ({
      organization_slug: m.organization_slug,
      role: m.role,
    })),
  )

  const [resetOpen, setResetOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)

  const { data: availableRoles = [], isLoading: rolesLoading } = useQuery({
    queryFn: ({ signal }) => getRoles(signal),
    queryKey: ['roles'],
  })

  const { data: localAuth } = useQuery({
    queryFn: ({ signal }) => getLocalAuthConfig(signal),
    queryKey: ['admin', 'local-auth'],
  })
  const localAuthEnabled = localAuth?.enabled ?? false

  const {
    handleFieldChange,
    setTouched,
    setValidationErrors,
    touched,
    validationErrors,
  } = useFormScaffold()

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

  const validateEmail = (value: string): string => {
    if (!value.trim()) return 'Email is required'
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) return 'Invalid email format'
    return ''
  }

  const validateDisplayName = (value: string): string => {
    if (!value.trim()) return 'Display name is required'
    return ''
  }

  const passwordRequired = localAuthEnabled && (changePassword || !isEditing)

  const validatePassword = (value: string): string => {
    if (passwordRequired) {
      if (!value) return 'Password is required'
      if (value.length < 12) return 'Password must be at least 12 characters'
      if (passwordStrength.score < 3) return 'Password is too weak'
    }
    return ''
  }

  const validateConfirmPassword = (value: string): string => {
    if (passwordRequired && value !== password) {
      return 'Passwords do not match'
    }
    return ''
  }

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}

    const emailError = validateEmail(email)
    if (emailError) errors.email = emailError

    const displayNameError = validateDisplayName(displayName)
    if (displayNameError) errors.display_name = displayNameError

    if (passwordRequired) {
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

  const formatDate = (value?: null | string) => {
    if (!value) return 'Never'
    return new Date(value).toLocaleString('en-US', {
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      month: 'short',
      year: 'numeric',
    })
  }

  const handleSave = () => {
    if (!validateForm()) {
      return
    }

    const userData: AdminUserCreate = {
      display_name: displayName.trim(),
      email: email.trim(),
      email_notifications: emailNotifications,
      is_active: isActive,
      is_admin: isAdmin,
      is_service_account: false,
      organization_slug: organizationSlug,
      role_slug: roleSlug,
    }

    if (isEditing) {
      userData.organizations = memberships
    }

    if (localAuthEnabled && (changePassword || !isEditing)) {
      userData.password = password
    }

    onSave(userData)
  }

  return (
    <div className="space-y-6">
      {isEditing ? (
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-center gap-3">
            <Gravatar
              alt={user.display_name}
              className="size-12 rounded-full"
              email={user.email}
              size={48}
            />
            <div className="min-w-0">
              <h1 className="truncate text-base font-medium text-primary">
                {user.display_name}
              </h1>
              <p className="font-mono text-xs text-tertiary">{user.email}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              disabled={isLoading}
              onClick={onCancel}
              type="button"
              variant="outline"
            >
              <XIcon className="mr-2 h-4 w-4" />
              Cancel
            </Button>
            <Button disabled={isLoading} onClick={handleSave} type="button">
              <Save className="mr-2 h-4 w-4" />
              {isLoading ? 'Saving...' : 'Save Changes'}
            </Button>
          </div>
        </div>
      ) : (
        <FormHeader
          createLabel="Create User"
          isEditing={false}
          isLoading={isLoading}
          onCancel={onCancel}
          onSave={handleSave}
          subtitle="Add a new user account to the system"
          title="Create New User"
        />
      )}

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

      <Card className="overflow-hidden p-0">
        {/* Identity */}
        <FormSection
          description="Profile fields shown across Imbi."
          label="Identity"
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FormField
              error={validationErrors.display_name}
              htmlFor="user-display-name"
              label="Display Name"
              required
              touched={touched.display_name}
            >
              <Input
                disabled={isLoading}
                id="user-display-name"
                onBlur={() => {
                  setTouched({ ...touched, display_name: true })
                  const e = validateDisplayName(displayName)
                  if (e)
                    setValidationErrors({
                      ...validationErrors,
                      display_name: e,
                    })
                }}
                onChange={(e) => {
                  setDisplayName(e.target.value)
                  handleFieldChange('display_name')
                }}
                placeholder="John Doe"
                value={displayName}
              />
            </FormField>
            <div>
              <FormField
                error={validationErrors.email}
                htmlFor="user-email"
                label="Email"
                required
                touched={touched.email}
              >
                <Input
                  disabled={isLoading || isEditing}
                  id="user-email"
                  onBlur={() => {
                    setTouched({ ...touched, email: true })
                    const e = validateEmail(email)
                    if (e)
                      setValidationErrors({ ...validationErrors, email: e })
                  }}
                  onChange={(e) => {
                    setEmail(e.target.value)
                    handleFieldChange('email')
                  }}
                  placeholder="john.doe@company.com"
                  readOnly={isEditing}
                  type="email"
                  value={email}
                />
              </FormField>
              {email && validateEmail(email) === '' && (
                <p className="mt-1.5 text-xs text-tertiary">
                  Avatar uses{' '}
                  <a
                    className="text-amber-text hover:underline"
                    href="https://gravatar.com"
                    rel="noopener noreferrer"
                    target="_blank"
                  >
                    Gravatar
                  </a>{' '}
                  for this address.
                </p>
              )}
            </div>
          </div>
        </FormSection>

        {/* Access */}
        <FormSection
          description="What this user can do across the system, and whether they can sign in at all."
          label="Access"
        >
          <div>
            <div className="mb-1.5 text-sm text-secondary">Account type</div>
            <div
              aria-label="Account type"
              className="inline-flex gap-1 rounded-md border border-tertiary bg-secondary p-1"
              role="radiogroup"
            >
              <button
                aria-checked={!isAdmin}
                className={cn(
                  'inline-flex h-8 items-center gap-2 rounded px-3 text-sm font-medium transition-colors',
                  !isAdmin
                    ? 'bg-background text-primary shadow-sm'
                    : 'text-secondary hover:text-primary',
                )}
                disabled={isLoading}
                onClick={() => setIsAdmin(false)}
                role="radio"
                type="button"
              >
                <User className="h-3.5 w-3.5" />
                Regular user
              </button>
              <button
                aria-checked={isAdmin}
                className={cn(
                  'inline-flex h-8 items-center gap-2 rounded px-3 text-sm font-medium transition-colors',
                  isAdmin
                    ? 'bg-background text-amber-700 shadow-sm dark:text-amber-400'
                    : 'text-secondary hover:text-primary',
                )}
                disabled={isLoading}
                onClick={() => setIsAdmin(true)}
                role="radio"
                type="button"
              >
                <Shield className="h-3.5 w-3.5" />
                Administrator
              </button>
            </div>
            {isAdmin ? (
              <p className="mt-2 flex items-start gap-1.5 text-sm text-amber-700 dark:text-amber-400">
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                Super-user with full system access (bypasses all permission
                checks)
              </p>
            ) : (
              <p className="mt-2 flex items-start gap-1.5 text-sm text-tertiary">
                <Info className="mt-0.5 h-3.5 w-3.5 flex-shrink-0" />
                Permissions come from organization roles below.
              </p>
            )}
          </div>

          <div className="mt-2">
            <ToggleRow
              description="Inactive accounts cannot authenticate or use the API."
              disabled={isLoading}
              id="user-active"
              label="Account active"
              onChange={setIsActive}
              value={isActive}
            />
            <ToggleRow
              description="Send system notifications, deploy summaries, and incident alerts by email."
              disabled={isLoading}
              id="user-email-notif"
              label="Email notifications"
              onChange={setEmailNotifications}
              value={emailNotifications}
            />
          </div>
        </FormSection>

        {/* Memberships */}
        {isEditing && (
          <FormSection
            description="Organizations this user belongs to and the role they hold in each. Roles drive permissions."
            label="Memberships"
          >
            <div className="overflow-hidden rounded-md border border-tertiary">
              <div className="grid grid-cols-[1fr_180px] gap-4 border-b border-tertiary bg-secondary px-4 py-2.5 text-xs font-semibold uppercase tracking-wider text-tertiary">
                <span>Organization</span>
                <span>Role</span>
              </div>
              {organizations.map((org) => {
                const idx = memberships.findIndex(
                  (m) => m.organization_slug === org.slug,
                )
                const checked = idx !== -1
                return (
                  <label
                    className={cn(
                      'grid cursor-pointer grid-cols-[1fr_180px] items-center gap-4 border-b border-tertiary px-4 py-2.5 last:border-b-0 hover:bg-secondary/50',
                      !checked && 'opacity-60',
                    )}
                    key={org.slug}
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <input
                        checked={checked}
                        className="size-4 rounded border-tertiary"
                        disabled={isLoading}
                        onChange={(e) => {
                          if (e.target.checked) {
                            const defaultRole = availableRoles[0]?.slug ?? ''
                            setMemberships([
                              ...memberships,
                              {
                                organization_slug: org.slug,
                                role: defaultRole,
                              },
                            ])
                          } else {
                            setMemberships(
                              memberships.filter(
                                (m) => m.organization_slug !== org.slug,
                              ),
                            )
                          }
                        }}
                        type="checkbox"
                      />
                      <span className="truncate text-sm font-medium text-primary">
                        {org.name}
                      </span>
                    </div>
                    <select
                      className="rounded-md border border-input bg-background px-2 py-1 text-sm text-foreground disabled:cursor-not-allowed disabled:opacity-50"
                      disabled={!checked || isLoading || rolesLoading}
                      onChange={(e) => {
                        const next = [...memberships]
                        next[idx] = { ...next[idx], role: e.target.value }
                        setMemberships(next)
                      }}
                      onClick={(e) => e.stopPropagation()}
                      value={checked ? memberships[idx].role : ''}
                    >
                      {availableRoles.map((r) => (
                        <option key={r.slug} value={r.slug}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )
              })}
            </div>
          </FormSection>
        )}

        {/* Initial organization (creation only) */}
        {!isEditing && (
          <FormSection
            description="Users must belong to at least one organization with a role to have any permissions."
            label="Membership"
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <FormField
                error={validationErrors.organization_slug}
                label="Organization"
                required
                touched={touched.organization_slug}
              >
                <select
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
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
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
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
          </FormSection>
        )}

        {/* Security */}
        {localAuthEnabled && (
          <FormSection
            description="Sensitive actions. Each one is recorded in the operations log."
            label="Security"
          >
            {isEditing && (
              <div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-tertiary py-3 first:pt-0">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-primary">
                      Password
                    </div>
                    <p className="mt-0.5 text-sm text-secondary">
                      Reset to issue a temporary local password the user must
                      change at next sign-in.
                    </p>
                    {changePassword && password && (
                      <p className="mt-1 font-mono text-xs text-amber-700 dark:text-amber-400">
                        Will reset on save
                      </p>
                    )}
                  </div>
                  <Button
                    disabled={isLoading}
                    onClick={() => setResetOpen(true)}
                    size="sm"
                    type="button"
                    variant="outline"
                  >
                    <KeyRound className="mr-2 h-4 w-4" />
                    Reset password
                  </Button>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 border-b border-tertiary py-3">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-primary">
                      Multi-factor authentication
                    </div>
                    <p className="mt-0.5 text-sm text-secondary">
                      Force re-enrollment of multi-factor authentication on next
                      sign-in.
                    </p>
                  </div>
                  <Button disabled size="sm" type="button" variant="outline">
                    <ShieldAlert className="mr-2 h-4 w-4" />
                    Reset MFA
                  </Button>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 py-3 last:pb-0">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-primary">
                      Active sessions
                    </div>
                    <p className="mt-0.5 text-sm text-secondary">
                      Revoke all active sessions and force a fresh sign-in
                      everywhere.
                    </p>
                  </div>
                  <Button disabled size="sm" type="button" variant="outline">
                    <LogOut className="mr-2 h-4 w-4" />
                    Sign out everywhere
                  </Button>
                </div>
              </div>
            )}

            {!isEditing && (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <FormField
                    error={validationErrors.password}
                    htmlFor="user-password"
                    label="Password"
                    required
                    touched={touched.password}
                  >
                    <div className="relative">
                      <Input
                        className="pr-10"
                        disabled={isLoading}
                        id="user-password"
                        onBlur={() => {
                          setTouched({ ...touched, password: true })
                          const e = validatePassword(password)
                          if (e)
                            setValidationErrors({
                              ...validationErrors,
                              password: e,
                            })
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
                        <div className="h-2 flex-1 overflow-hidden rounded-full bg-secondary">
                          <div
                            className={cn(
                              'h-full transition-all',
                              passwordStrength.color === 'red' && 'bg-red-500',
                              passwordStrength.color === 'yellow' &&
                                'bg-yellow-500',
                              passwordStrength.color === 'green' &&
                                'bg-green-500',
                            )}
                            style={{
                              width: `${(passwordStrength.score / 6) * 100}%`,
                            }}
                          />
                        </div>
                        <span
                          className={cn(
                            'text-xs',
                            passwordStrength.color === 'red' && 'text-red-500',
                            passwordStrength.color === 'yellow' &&
                              'text-yellow-500',
                            passwordStrength.color === 'green' &&
                              'text-green-500',
                          )}
                        >
                          {passwordStrength.label}
                        </span>
                      </div>
                      <ul className="space-y-0.5 text-xs text-secondary">
                        {[
                          {
                            label: 'At least 12 characters',
                            test: password.length >= 12,
                          },
                          {
                            label: 'Uppercase letter',
                            test: /[A-Z]/.test(password),
                          },
                          {
                            label: 'Lowercase letter',
                            test: /[a-z]/.test(password),
                          },
                          { label: 'Number', test: /[0-9]/.test(password) },
                          {
                            label: 'Special character',
                            test: /[^a-zA-Z0-9]/.test(password),
                          },
                        ].map((req) => (
                          <li
                            className={cn(
                              'flex items-center gap-1',
                              req.test && 'text-green-600 dark:text-green-400',
                            )}
                            key={req.label}
                          >
                            {req.test ? (
                              <Check className="h-3 w-3" />
                            ) : (
                              <XIcon className="h-3 w-3" />
                            )}
                            {req.label}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                <FormField
                  error={validationErrors.confirmPassword}
                  htmlFor="user-confirm-password"
                  label="Confirm Password"
                  required
                  touched={touched.confirmPassword}
                >
                  <Input
                    disabled={isLoading}
                    id="user-confirm-password"
                    onBlur={() => {
                      setTouched({ ...touched, confirmPassword: true })
                      const e = validateConfirmPassword(confirmPassword)
                      if (e)
                        setValidationErrors({
                          ...validationErrors,
                          confirmPassword: e,
                        })
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
            )}
          </FormSection>
        )}

        {isEditing && (
          <div className="flex items-center gap-1.5 border-t border-tertiary bg-secondary px-6 py-3 text-xs text-tertiary">
            <Info className="h-3 w-3" />
            <span>Created {formatDate(user.created_at)}</span>
            <span>·</span>
            <span>
              Last sign-in{' '}
              <span className="font-mono">{formatDate(user.last_login)}</span>
            </span>
          </div>
        )}
      </Card>

      {isEditing && onDelete && (
        <div className="grid grid-cols-[1fr_auto] items-center gap-4 rounded-lg border border-danger bg-card p-5">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-danger">
              <Trash2 className="h-4 w-4" />
              Delete user
            </div>
            <p className="mt-1 text-sm text-secondary">
              Removes the account and revokes all tokens. Project ownership is
              reassigned to the organization owner.
            </p>
          </div>
          <Button
            disabled={isDeleting}
            onClick={() => setDeleteOpen(true)}
            type="button"
            variant="destructive"
          >
            {isDeleting ? 'Deleting...' : 'Delete user'}
          </Button>
        </div>
      )}

      {isEditing && (
        <ResetPasswordModal
          email={user.email}
          isLoading={isLoading}
          onClose={() => setResetOpen(false)}
          onConfirm={(newPassword) => {
            setPassword(newPassword)
            setConfirmPassword(newPassword)
            setChangePassword(true)
            setResetOpen(false)
          }}
          open={resetOpen}
        />
      )}

      {isEditing && onDelete && (
        <ConfirmDialog
          confirmLabel="Delete user"
          description={`Permanently delete ${user.display_name}? This cannot be undone.`}
          onCancel={() => setDeleteOpen(false)}
          onConfirm={() => {
            setDeleteOpen(false)
            onDelete(user)
          }}
          open={deleteOpen}
          title="Delete user"
        />
      )}
    </div>
  )
}

function FormSection({ children, description, label }: FormSectionProps) {
  return (
    <div className="grid grid-cols-1 gap-6 border-t border-tertiary px-6 py-6 first:border-t-0 md:grid-cols-[200px_1fr] md:gap-8">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wider text-tertiary">
          {label}
        </div>
        <p className="mt-1.5 text-sm text-secondary">{description}</p>
      </div>
      <div className="min-w-0 space-y-4">{children}</div>
    </div>
  )
}

function RadioDot({ active }: { active: boolean }) {
  return (
    <div
      className={cn(
        'relative mt-0.5 size-4 flex-shrink-0 rounded-full border-[1.5px]',
        active ? 'border-amber-border' : 'border-secondary',
      )}
    >
      {active && (
        <div className="absolute inset-1 rounded-full bg-amber-border" />
      )}
    </div>
  )
}

function ResetPasswordModal({
  email,
  isLoading,
  onClose,
  onConfirm,
  open,
}: ResetPasswordModalProps) {
  const [mode, setMode] = useState<'auto' | 'create'>('auto')
  const [generated, setGenerated] = useState('')
  const [manual, setManual] = useState('')
  const [confirmManual, setConfirmManual] = useState('')
  const [copied, setCopied] = useState(false)

  const generatePassword = () => {
    const charset =
      'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789!@#$%^&*'
    const arr = new Uint32Array(16)
    crypto.getRandomValues(arr)
    return Array.from(arr, (n) => charset[n % charset.length]).join('')
  }

  useEffect(() => {
    if (open) {
      setMode('auto')
      setGenerated(generatePassword())
      setManual('')
      setConfirmManual('')
      setCopied(false)
    }
  }, [open])

  const canConfirm =
    mode === 'auto' ? !!generated : !!manual && manual === confirmManual

  return (
    <Dialog
      onOpenChange={(o) => {
        if (!o) onClose()
      }}
      open={open}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription className="font-mono">{email}</DialogDescription>
        </DialogHeader>

        <div className="space-y-3 p-6">
          <button
            className={cn(
              'grid w-full grid-cols-[18px_1fr] items-start gap-3 rounded-md border p-3 text-left transition-colors',
              mode === 'auto'
                ? 'border-amber-border bg-amber-bg'
                : 'border-tertiary hover:bg-secondary',
            )}
            onClick={() => setMode('auto')}
            type="button"
          >
            <RadioDot active={mode === 'auto'} />
            <div>
              <div className="text-sm font-medium text-primary">
                Automatically generate a password
              </div>
              <p className="mt-0.5 text-xs text-secondary">
                The password will be displayed below — copy it before closing.
              </p>
              {mode === 'auto' && (
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 truncate rounded border border-tertiary bg-background px-2 py-1.5 font-mono text-xs text-primary">
                    {generated}
                  </code>
                  <Button
                    onClick={(e) => {
                      e.stopPropagation()
                      setGenerated(generatePassword())
                      setCopied(false)
                    }}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    <RefreshCw className="h-3.5 w-3.5" />
                  </Button>
                  <Button
                    onClick={(e) => {
                      e.stopPropagation()
                      void navigator.clipboard.writeText(generated)
                      setCopied(true)
                    }}
                    size="sm"
                    type="button"
                    variant="ghost"
                  >
                    {copied ? (
                      <Check className="h-3.5 w-3.5" />
                    ) : (
                      <Copy className="h-3.5 w-3.5" />
                    )}
                  </Button>
                </div>
              )}
            </div>
          </button>

          <button
            className={cn(
              'grid w-full grid-cols-[18px_1fr] items-start gap-3 rounded-md border p-3 text-left transition-colors',
              mode === 'create'
                ? 'border-amber-border bg-amber-bg'
                : 'border-tertiary hover:bg-secondary',
            )}
            onClick={() => setMode('create')}
            type="button"
          >
            <RadioDot active={mode === 'create'} />
            <div>
              <div className="text-sm font-medium text-primary">
                Create password
              </div>
              <p className="mt-0.5 text-xs text-secondary">
                Set a temporary password the user must change at next sign-in.
              </p>
              {mode === 'create' && (
                <div className="mt-2 space-y-2">
                  <Input
                    onChange={(e) => setManual(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    placeholder="Minimum 12 characters"
                    type="password"
                    value={manual}
                  />
                  <Input
                    onChange={(e) => setConfirmManual(e.target.value)}
                    onClick={(e) => e.stopPropagation()}
                    placeholder="Confirm password"
                    type="password"
                    value={confirmManual}
                  />
                </div>
              )}
            </div>
          </button>
        </div>

        <DialogFooter>
          <Button
            disabled={isLoading}
            onClick={onClose}
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button
            disabled={!canConfirm || isLoading}
            onClick={() => onConfirm(mode === 'auto' ? generated : manual)}
            type="button"
          >
            <KeyRound className="mr-2 h-4 w-4" />
            Reset password
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ToggleRow({
  description,
  disabled,
  id,
  label,
  onChange,
  value,
}: ToggleRowProps) {
  return (
    <div className="grid grid-cols-[1fr_auto] items-center gap-4 border-b border-tertiary py-3 first:pt-0 last:border-b-0 last:pb-0">
      <div>
        <label
          className="block cursor-pointer text-sm font-medium text-primary"
          htmlFor={id}
        >
          {label}
        </label>
        <p className="mt-0.5 text-sm text-secondary">{description}</p>
      </div>
      <Switch
        checked={value}
        disabled={disabled}
        id={id}
        onCheckedChange={onChange}
      />
    </div>
  )
}
