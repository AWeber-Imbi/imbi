import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Trash2 } from 'lucide-react'

import { getRoles } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useDirtyState } from '@/hooks/useDirtyState'
import { useFormScaffold } from '@/hooks/useFormScaffold'
import type {
  ApiKeyCreated,
  ClientCredentialCreated,
  Role,
  ServiceAccount,
  ServiceAccountCreate,
} from '@/types'

import { ApiKeysSection } from './ApiKeysSection'
import { AvatarUpload } from './AvatarUpload'
import { ClientCredentialsSection } from './ClientCredentialsSection'
import { OrgMembershipsCard } from './OrgMembershipsCard'
import { useServiceAccountMutations } from './useServiceAccountMutations'

// ── Interfaces (alphabetical) ─────────────────────────────────────────────

interface ActiveToggleRowProps {
  description: string
  disabled?: boolean
  label: string
  onChange: (v: boolean) => void
  value: boolean
}

interface EditSectionsLeftProps {
  account: ServiceAccount
  availableRoles: Role[]
  rolesError: boolean
  rolesLoading: boolean
}

interface IdentityCardEditProps {
  account: ServiceAccount
  description: string
  displayName: string
  isActive: boolean
  isLoading: boolean
  onActiveChange: (v: boolean) => void
  onBlurDisplayName: () => void
  onDescriptionChange: (v: string) => void
  onDisplayNameChange: (v: string) => void
  touched: Record<string, boolean>
  validationErrors: Record<string, string>
}

interface ServiceAccountFormProps {
  account: null | ServiceAccount
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onDelete?: () => void
  onSave: (data: ServiceAccountCreate) => void
}

// ── Components (alphabetical) ─────────────────────────────────────────────

export function ServiceAccountForm({
  account,
  error,
  isLoading = false,
  onCancel,
  onDelete,
  onSave,
}: ServiceAccountFormProps) {
  const isEditing = !!account

  const [slug, setSlug] = useState(account?.slug || '')
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(isEditing)
  const [displayName, setDisplayName] = useState(account?.display_name || '')
  const [description, setDescription] = useState(account?.description || '')
  const [isActive, setIsActive] = useState(account?.is_active ?? true)

  const { organizations } = useOrganization()
  const [organizationSlug, setOrganizationSlug] = useState(
    organizations.length === 1 ? organizations[0].slug : '',
  )
  const [roleSlug, setRoleSlug] = useState('')

  const {
    data: availableRoles = [],
    isError: rolesError,
    isLoading: rolesLoading,
  } = useQuery({
    queryFn: ({ signal }) => getRoles(signal),
    queryKey: ['roles'],
  })

  const {
    handleFieldChange,
    setTouched,
    setValidationErrors,
    touched,
    validationErrors,
  } = useFormScaffold()

  const [initialFormData] = useState(() => ({
    description: account?.description ?? '',
    display_name: account?.display_name ?? '',
    is_active: account?.is_active ?? true,
    organization_slug: organizations.length === 1 ? organizations[0].slug : '',
    role_slug: '',
    slug: account?.slug ?? '',
  }))
  const currentFormData = {
    description,
    display_name: displayName,
    is_active: isActive,
    organization_slug: organizationSlug,
    role_slug: roleSlug,
    slug,
  }
  useDirtyState(initialFormData, currentFormData, { enabled: !isLoading })

  const validateSlug = (value: string): string => {
    if (!value.trim()) return 'Slug is required'
    if (!/^[a-z][a-z0-9-]*$/.test(value)) {
      return 'Slug must start with a lowercase letter and contain only lowercase letters, numbers, and hyphens'
    }
    return ''
  }

  const validateDisplayName = (value: string): string => {
    if (!value.trim()) return 'Display name is required'
    return ''
  }

  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}

    const slugError = validateSlug(slug)
    if (slugError) errors.slug = slugError

    const displayNameError = validateDisplayName(displayName)
    if (displayNameError) errors.display_name = displayNameError

    if (!isEditing) {
      if (!organizationSlug)
        errors.organization_slug = 'Organization is required'
      if (!roleSlug) errors.role_slug = 'Role is required'
    }

    setValidationErrors(errors)
    setTouched({
      display_name: true,
      organization_slug: true,
      role_slug: true,
      slug: true,
    })

    return Object.keys(errors).length === 0
  }

  const handleSave = () => {
    if (!validateForm()) return
    onSave({
      description: description.trim() || null,
      display_name: displayName.trim(),
      is_active: isActive,
      organization_slug: organizationSlug,
      role_slug: roleSlug,
      slug: slug.trim(),
    })
  }

  const handleDisplayNameChange = (value: string) => {
    setDisplayName(value)
    if (!slugManuallyEdited) {
      setSlug(toSlug(value))
    }
    handleFieldChange('display_name')
  }

  const handleSlugChange = (value: string) => {
    setSlug(toSlug(value))
    setSlugManuallyEdited(true)
    handleFieldChange('slug')
  }

  const header = (
    <FormHeader
      createLabel="Create Service Account"
      isEditing={isEditing}
      isLoading={isLoading}
      onCancel={onCancel}
      onSave={handleSave}
      subtitle={
        isEditing
          ? undefined
          : 'Create an automated service account for API access'
      }
      title={isEditing ? 'Edit Service Account' : 'Create Service Account'}
    />
  )

  const errorBanner = error && (
    <div className="border-danger bg-danger rounded-lg border p-4">
      <div className="flex items-start gap-3">
        <AlertCircle className="text-danger size-5 shrink-0" />
        <div>
          <div className="text-danger font-medium">
            Failed to save service account
          </div>
          <div className="text-danger mt-1 text-sm">
            {error?.response?.data?.detail ||
              error?.message ||
              'An error occurred'}
          </div>
        </div>
      </div>
    </div>
  )

  if (isEditing && account) {
    return (
      <div className="space-y-6">
        {header}
        {errorBanner}
        <div className="grid grid-cols-2 items-start gap-6">
          {/* Left column: identity + org memberships */}
          <div className="space-y-6">
            <IdentityCardEdit
              account={account}
              description={description}
              displayName={displayName}
              isActive={isActive}
              isLoading={isLoading}
              onActiveChange={setIsActive}
              onBlurDisplayName={() => {
                setTouched({ ...touched, display_name: true })
                const err = validateDisplayName(displayName)
                if (err)
                  setValidationErrors({
                    ...validationErrors,
                    display_name: err,
                  })
              }}
              onDescriptionChange={(v) => {
                setDescription(v)
                handleFieldChange('description')
              }}
              onDisplayNameChange={(v) => {
                setDisplayName(v)
                handleFieldChange('display_name')
              }}
              touched={touched}
              validationErrors={validationErrors}
            />
            <EditSectionsLeft
              account={account}
              availableRoles={availableRoles}
              rolesError={rolesError}
              rolesLoading={rolesLoading}
            />
          </div>

          {/* Right column: credentials + API keys */}
          <EditSectionsRight account={account} />
        </div>

        {/* Danger zone (full width) */}
        {onDelete && (
          <DangerZoneCard
            displayName={account.display_name}
            onDelete={onDelete}
          />
        )}
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {header}
      {errorBanner}

      {/* Identity card (create mode) */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-2 gap-4">
            {/* Display Name */}
            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Display Name <span className="text-red-500">*</span>
              </label>
              <Input
                disabled={isLoading}
                onBlur={() => {
                  setTouched({ ...touched, display_name: true })
                  const err = validateDisplayName(displayName)
                  if (err)
                    setValidationErrors({
                      ...validationErrors,
                      display_name: err,
                    })
                }}
                onChange={(e) => handleDisplayNameChange(e.target.value)}
                placeholder="CI/CD Pipeline"
                value={displayName}
              />
              {touched.display_name && validationErrors.display_name && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.display_name}
                </p>
              )}
            </div>

            {/* Slug */}
            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Slug <span className="text-red-500">*</span>
              </label>
              <Input
                disabled={isLoading}
                onBlur={() => {
                  setTouched({ ...touched, slug: true })
                  const err = validateSlug(slug)
                  if (err)
                    setValidationErrors({ ...validationErrors, slug: err })
                }}
                onChange={(e) => handleSlugChange(e.target.value)}
                placeholder="my-service-account"
                value={slug}
              />
              <p className="text-tertiary mt-1 text-xs">
                Lowercase letters, numbers, and hyphens only.
              </p>
              {touched.slug && validationErrors.slug && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.slug}
                </p>
              )}
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="text-secondary mb-1.5 flex items-center justify-between text-sm">
              <span>Description</span>
              <span className="text-tertiary text-xs">
                {description.length}/500
              </span>
            </label>
            <textarea
              className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full rounded-md border px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500 focus:outline-none"
              disabled={isLoading}
              maxLength={500}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What does this service account do?"
              rows={3}
              value={description}
            />
          </div>

          {/* Active toggle */}
          <ActiveToggleRow
            description="Inactive service accounts cannot authenticate via API or OAuth."
            disabled={isLoading}
            label="Account active"
            onChange={setIsActive}
            value={isActive}
          />
        </CardContent>
      </Card>

      {/* Organization Membership (creation only) */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <p className="text-secondary mb-4 text-sm">
            Service accounts must belong to at least one organization with a
            role to have any permissions.
          </p>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500 focus:outline-none"
                disabled={isLoading || organizations.length === 1}
                onChange={(e) => {
                  setOrganizationSlug(e.target.value)
                  handleFieldChange('organization_slug')
                }}
                value={organizationSlug}
              >
                {organizations.length !== 1 && (
                  <option value="">Select an organization...</option>
                )}
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

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Role <span className="text-red-500">*</span>
              </label>
              {rolesLoading ? (
                <p className="text-secondary text-sm">Loading roles...</p>
              ) : rolesError ? (
                <p className="text-danger text-sm">
                  Failed to load roles. Please refresh and try again.
                </p>
              ) : (
                <select
                  className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500 focus:outline-none"
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
              {touched.role_slug && validationErrors.role_slug && (
                <p className="mt-1 text-sm text-red-600">
                  {validationErrors.role_slug}
                </p>
              )}
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function ActiveToggleRow({
  description,
  disabled,
  label,
  onChange,
  value,
}: ActiveToggleRowProps) {
  return (
    <div className="border-tertiary bg-secondary flex items-center gap-3 rounded-lg border px-3 py-2.5">
      <div className="flex-1">
        <div className="text-primary text-sm font-medium">{label}</div>
        <div className="text-tertiary text-xs">{description}</div>
      </div>
      <button
        aria-checked={value}
        className={`focus-visible:ring-action relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${
          value
            ? 'bg-[var(--border-color-success)]'
            : 'bg-[var(--border-color-primary)]'
        }`}
        disabled={disabled}
        onClick={() => onChange(!value)}
        role="switch"
        type="button"
      >
        <span
          className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow transition duration-150 ease-in-out ${
            value ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}

function DangerZoneCard({
  displayName,
  onDelete,
}: {
  displayName: string
  onDelete: () => void
}) {
  return (
    <Card className="border-danger from-danger/30 bg-linear-to-b to-transparent">
      <CardContent className="pt-6">
        <div className="mb-4 flex items-center gap-2">
          <AlertCircle className="text-danger size-4" />
          <h3 className="text-danger text-sm font-semibold">Danger zone</h3>
        </div>
        <div className="flex items-center justify-between">
          <div>
            <div className="text-primary text-sm font-medium">
              Delete service account
            </div>
            <div className="text-tertiary text-xs">
              Permanently remove this account and revoke all credentials. This
              cannot be undone.
            </div>
          </div>
          <Button
            className="ml-6 shrink-0"
            onClick={() => {
              if (
                confirm(
                  `Delete "${displayName}"? This will revoke all credentials and cannot be undone.`,
                )
              ) {
                onDelete()
              }
            }}
            size="sm"
            variant="outline"
          >
            <Trash2 className="text-danger mr-2 size-3.5" />
            <span className="text-danger">Delete account</span>
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

function EditSectionsLeft({
  account,
  availableRoles,
  rolesError,
  rolesLoading,
}: EditSectionsLeftProps) {
  const { addOrgMutation, removeOrgMutation, updateOrgRoleMutation } =
    useServiceAccountMutations(account)

  return (
    <OrgMembershipsCard
      account={account}
      addOrgMutation={addOrgMutation}
      availableRoles={availableRoles}
      onConfirmRemove={(orgSlug, orgName) => {
        if (confirm(`Remove ${account.display_name} from ${orgName}?`)) {
          removeOrgMutation.mutate(orgSlug)
        }
      }}
      removeOrgMutation={removeOrgMutation}
      rolesError={rolesError}
      rolesLoading={rolesLoading}
      updateOrgRoleMutation={updateOrgRoleMutation}
    />
  )
}

function EditSectionsRight({ account }: { account: ServiceAccount }) {
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<ApiKeyCreated | null>(
    null,
  )
  const [newlyCreatedCredential, setNewlyCreatedCredential] =
    useState<ClientCredentialCreated | null>(null)

  const {
    createApiKeyMutation,
    createCredentialMutation,
    revokeApiKeyMutation,
    revokeCredentialMutation,
    rotateApiKeyMutation,
    rotateCredentialMutation,
  } = useServiceAccountMutations(account)

  return (
    <div className="space-y-6">
      <ClientCredentialsSection
        account={account}
        createCredentialMutation={createCredentialMutation}
        newlyCreatedCredential={newlyCreatedCredential}
        onConfirmRevoke={(clientId) => {
          if (
            confirm('Revoke this credential? This action cannot be undone.')
          ) {
            revokeCredentialMutation.mutate(clientId)
          }
        }}
        onConfirmRotate={(clientId) => {
          if (
            confirm(
              'Rotate this credential? The old secret will stop working immediately.',
            )
          ) {
            rotateCredentialMutation.mutate(clientId, {
              onSuccess: (data) => setNewlyCreatedCredential(data),
            })
          }
        }}
        onNewlyCreatedCredentialChange={setNewlyCreatedCredential}
        revokeCredentialMutation={revokeCredentialMutation}
        rotateCredentialMutation={rotateCredentialMutation}
      />

      <ApiKeysSection
        account={account}
        createApiKeyMutation={createApiKeyMutation}
        newlyCreatedKey={newlyCreatedKey}
        onConfirmRevoke={(keyId) => {
          if (confirm('Revoke this API key? This action cannot be undone.')) {
            revokeApiKeyMutation.mutate(keyId)
          }
        }}
        onConfirmRotate={(keyId) => {
          if (
            confirm(
              'Rotate this API key? The old key will stop working immediately.',
            )
          ) {
            rotateApiKeyMutation.mutate(keyId, {
              onSuccess: (data) => setNewlyCreatedKey(data),
            })
          }
        }}
        onNewlyCreatedKeyChange={setNewlyCreatedKey}
        revokeApiKeyMutation={revokeApiKeyMutation}
        rotateApiKeyMutation={rotateApiKeyMutation}
      />
    </div>
  )
}

function IdentityCardEdit({
  account,
  description,
  displayName,
  isActive,
  isLoading,
  onActiveChange,
  onBlurDisplayName,
  onDescriptionChange,
  onDisplayNameChange,
  touched,
  validationErrors,
}: IdentityCardEditProps) {
  const { removeAvatarMutation, uploadAvatarMutation } =
    useServiceAccountMutations(account)

  return (
    <Card>
      <CardContent className="space-y-4 pt-6">
        {/* Display name + slug in one row */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-secondary mb-1.5 block text-sm">
              Display name <span className="text-red-500">*</span>
            </label>
            <Input
              disabled={isLoading}
              onBlur={onBlurDisplayName}
              onChange={(e) => onDisplayNameChange(e.target.value)}
              placeholder="e.g. GitHub Integration"
              value={displayName}
            />
            {touched.display_name && validationErrors.display_name && (
              <p className="mt-1 text-sm text-red-600">
                {validationErrors.display_name}
              </p>
            )}
          </div>
          <div>
            <label className="text-secondary mb-1.5 flex items-center justify-between text-sm">
              <span>Slug</span>
              <span className="text-tertiary text-xs">
                URL identifier · read-only
              </span>
            </label>
            <Input
              className="text-tertiary font-mono"
              disabled
              value={account.slug}
            />
          </div>
        </div>

        {/* Description */}
        <div>
          <label className="text-secondary mb-1.5 flex items-center justify-between text-sm">
            <span>Description</span>
            <span className="text-tertiary text-xs">
              {description.length}/500
            </span>
          </label>
          <textarea
            className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full rounded-md border px-3 py-2 text-sm focus:border-transparent focus:ring-2 focus:ring-blue-500 focus:outline-none"
            disabled={isLoading}
            maxLength={500}
            onChange={(e) => onDescriptionChange(e.target.value)}
            placeholder="What does this service account do? Who owns it?"
            rows={3}
            value={description}
          />
        </div>

        {/* Avatar */}
        <div>
          <label className="text-secondary mb-1.5 block text-sm">Avatar</label>
          <div className="flex items-center gap-3">
            <AvatarUpload
              avatarUrl={account.avatar_url}
              displayName={displayName}
              isRemoving={removeAvatarMutation.isPending}
              isUploading={uploadAvatarMutation.isPending}
              onRemove={() => removeAvatarMutation.mutate()}
              onUpload={(file) => uploadAvatarMutation.mutate(file)}
            />
            <span className="text-tertiary text-xs">
              PNG or SVG · max 256 KB
            </span>
          </div>
        </div>

        {/* Active toggle */}
        <ActiveToggleRow
          description="Inactive service accounts cannot authenticate via API or OAuth."
          disabled={isLoading}
          label="Account active"
          onChange={onActiveChange}
          value={isActive}
        />
      </CardContent>
    </Card>
  )
}

function toSlug(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
}
