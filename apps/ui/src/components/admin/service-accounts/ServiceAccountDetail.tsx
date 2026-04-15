import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import {
  ArrowLeft,
  Edit2,
  Power,
  Clock,
  Calendar,
  Key,
  Copy,
  Plus,
  Trash2,
  AlertCircle,
  RotateCw,
  Shield,
  Tag,
  Building2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  listServiceAccountApiKeys,
  createServiceAccountApiKey,
  revokeServiceAccountApiKey,
  rotateServiceAccountApiKey,
  listClientCredentials,
  createClientCredential,
  revokeClientCredential,
  rotateClientCredential,
  addServiceAccountToOrg,
  updateServiceAccountOrgRole,
  removeServiceAccountFromOrg,
  getRoles,
} from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import type {
  ServiceAccount,
  ApiKey,
  ApiKeyCreated,
  ClientCredential,
  ClientCredentialCreated,
  ClientCredentialCreate,
  OrgMembership,
} from '@/types'

interface ServiceAccountDetailProps {
  account: ServiceAccount
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function ServiceAccountDetail({
  account,
  onEdit,
  onBack,
  isDarkMode,
}: ServiceAccountDetailProps) {
  const queryClient = useQueryClient()

  // API Keys state
  const [newKeyName, setNewKeyName] = useState('')
  const [showCreateKey, setShowCreateKey] = useState(false)
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<ApiKeyCreated | null>(
    null,
  )
  const [copiedId, setCopiedId] = useState<string | null>(null)

  // Client Credentials state
  const [showCreateCredential, setShowCreateCredential] = useState(false)
  const [credentialName, setCredentialName] = useState('')
  const [credentialDescription, setCredentialDescription] = useState('')
  const [credentialScopes, setCredentialScopes] = useState('')
  const [credentialExpiresDays, setCredentialExpiresDays] = useState('')
  const [newlyCreatedCredential, setNewlyCreatedCredential] =
    useState<ClientCredentialCreated | null>(null)

  // Organization membership state
  const { organizations: allOrgs } = useOrganization()
  const [showAddOrg, setShowAddOrg] = useState(false)
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newRoleSlug, setNewRoleSlug] = useState('')

  const { data: availableRoles = [], isError: rolesError } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  const memberOrgSlugs = new Set(
    (account.organizations ?? []).map((o) => o.organization_slug),
  )
  const availableOrgs = allOrgs.filter((o) => !memberOrgSlugs.has(o.slug))

  const addOrgMutation = useMutation({
    mutationFn: (data: { organization_slug: string; role_slug: string }) =>
      addServiceAccountToOrg(account.slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
      setShowAddOrg(false)
      setNewOrgSlug('')
      setNewRoleSlug('')
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to add to organization: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const updateOrgRoleMutation = useMutation({
    mutationFn: ({
      orgSlug,
      roleSlug,
    }: {
      orgSlug: string
      roleSlug: string
    }) =>
      updateServiceAccountOrgRole(account.slug, orgSlug, {
        role_slug: roleSlug,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to update role: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const removeOrgMutation = useMutation({
    mutationFn: (orgSlug: string) =>
      removeServiceAccountFromOrg(account.slug, orgSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['serviceAccounts'] })
      queryClient.invalidateQueries({
        queryKey: ['serviceAccount', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to remove from organization: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Reset all sensitive/form state when the viewed account changes
  useEffect(() => {
    setNewKeyName('')
    setShowCreateKey(false)
    setNewlyCreatedKey(null)
    setShowCreateCredential(false)
    setCredentialName('')
    setCredentialDescription('')
    setCredentialScopes('')
    setCredentialExpiresDays('')
    setNewlyCreatedCredential(null)
    setCopiedId(null)
    setShowAddOrg(false)
    setNewOrgSlug('')
    setNewRoleSlug('')
  }, [account.slug])

  // Fetch API keys
  const {
    data: apiKeys = [],
    isLoading: keysLoading,
    error: keysError,
  } = useQuery({
    queryKey: ['serviceAccountApiKeys', account.slug],
    queryFn: () => listServiceAccountApiKeys(account.slug),
  })

  // Fetch Client Credentials
  const {
    data: credentials = [],
    isLoading: credentialsLoading,
    error: credentialsError,
  } = useQuery({
    queryKey: ['clientCredentials', account.slug],
    queryFn: () => listClientCredentials(account.slug),
  })

  // API Key mutations
  const createKeyMutation = useMutation({
    mutationFn: (name: string) =>
      createServiceAccountApiKey(account.slug, { name }),
    onSuccess: (data: ApiKeyCreated) => {
      setNewlyCreatedKey(data)
      setShowCreateKey(false)
      setNewKeyName('')
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to create API key: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const revokeKeyMutation = useMutation({
    mutationFn: (keyId: string) =>
      revokeServiceAccountApiKey(account.slug, keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to revoke API key: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const rotateKeyMutation = useMutation({
    mutationFn: (keyId: string) =>
      rotateServiceAccountApiKey(account.slug, keyId),
    onSuccess: (data: ApiKeyCreated) => {
      setNewlyCreatedKey(data)
      queryClient.invalidateQueries({
        queryKey: ['serviceAccountApiKeys', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to rotate API key: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Client Credential mutations
  const createCredentialMutation = useMutation({
    mutationFn: (data: ClientCredentialCreate) =>
      createClientCredential(account.slug, data),
    onSuccess: (data: ClientCredentialCreated) => {
      setNewlyCreatedCredential(data)
      setShowCreateCredential(false)
      resetCredentialForm()
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to create credential: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const revokeCredentialMutation = useMutation({
    mutationFn: (clientId: string) =>
      revokeClientCredential(account.slug, clientId),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to revoke credential: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const rotateCredentialMutation = useMutation({
    mutationFn: (clientId: string) =>
      rotateClientCredential(account.slug, clientId),
    onSuccess: (data: ClientCredentialCreated) => {
      setNewlyCreatedCredential(data)
      queryClient.invalidateQueries({
        queryKey: ['clientCredentials', account.slug],
      })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to rotate credential: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const resetCredentialForm = () => {
    setCredentialName('')
    setCredentialDescription('')
    setCredentialScopes('')
    setCredentialExpiresDays('')
  }

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString(undefined, {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  const copyToClipboard = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedId(id)
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      alert('Failed to copy to clipboard')
    }
  }

  const handleCreateKey = () => {
    const name = newKeyName.trim() || 'default'
    createKeyMutation.mutate(name)
  }

  const handleRevokeKey = (keyId: string) => {
    if (
      confirm(
        'Are you sure you want to revoke this API key? This action cannot be undone.',
      )
    ) {
      revokeKeyMutation.mutate(keyId)
    }
  }

  const handleRotateKey = (keyId: string) => {
    if (
      confirm(
        'Are you sure you want to rotate this API key? The old key will stop working immediately.',
      )
    ) {
      rotateKeyMutation.mutate(keyId)
    }
  }

  const handleCreateCredential = () => {
    const scopes = credentialScopes
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    const expiresInDays =
      credentialExpiresDays.trim() === '' ? null : Number(credentialExpiresDays)

    if (
      expiresInDays !== null &&
      (!Number.isInteger(expiresInDays) || expiresInDays < 1)
    ) {
      alert('Expiration must be a positive whole number of days.')
      return
    }

    const data: ClientCredentialCreate = {
      name: credentialName.trim(),
      description: credentialDescription.trim() || null,
      scopes: scopes.length > 0 ? scopes : undefined,
      expires_in_days: expiresInDays,
    }
    createCredentialMutation.mutate(data)
  }

  const handleRevokeCredential = (clientId: string) => {
    if (
      confirm(
        'Are you sure you want to revoke this credential? This action cannot be undone.',
      )
    ) {
      revokeCredentialMutation.mutate(clientId)
    }
  }

  const handleRotateCredential = (clientId: string) => {
    if (
      confirm(
        'Are you sure you want to rotate this credential? The old secret will stop working immediately.',
      )
    ) {
      rotateCredentialMutation.mutate(clientId)
    }
  }

  const truncateClientId = (clientId: string) => {
    if (clientId.length <= 12) return clientId
    return `${clientId.substring(0, 12)}...`
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button
          variant="outline"
          onClick={onBack}
          className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Service Account info card */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div>
            <CardTitle>{account.display_name}</CardTitle>
            <p
              className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              {account.slug}
            </p>
          </div>
          <Button
            onClick={onEdit}
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Account
          </Button>
        </CardHeader>

        {/* Account Status */}
        <CardContent className="px-6 py-5">
          <div className="flex items-center gap-6">
            <div
              className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                account.is_active
                  ? isDarkMode
                    ? 'bg-green-900/30 text-green-400'
                    : 'bg-green-100 text-green-700'
                  : isDarkMode
                    ? 'bg-gray-700 text-gray-400'
                    : 'bg-gray-100 text-gray-600'
              }`}
            >
              <Power className="h-4 w-4" />
              {account.is_active ? 'Active' : 'Inactive'}
            </div>
            <div
              className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                isDarkMode
                  ? 'bg-purple-900/30 text-purple-400'
                  : 'bg-purple-100 text-purple-700'
              }`}
            >
              Service Account
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Organization Memberships */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Building2
              className={`h-5 w-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            />
            <CardTitle>Organization Memberships</CardTitle>
          </div>
          {availableOrgs.length > 0 && (
            <Button
              onClick={() => setShowAddOrg(!showAddOrg)}
              variant="outline"
              size="sm"
              className={
                isDarkMode
                  ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                  : ''
              }
            >
              <Plus className="mr-2 h-4 w-4" />
              Add to Organization
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {/* Add to Organization Form */}
          {showAddOrg && (
            <div
              className={`mb-4 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700'
                  : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Organization
                  </label>
                  <select
                    value={newOrgSlug}
                    onChange={(e) => setNewOrgSlug(e.target.value)}
                    className={`w-full rounded-md border px-3 py-2 text-sm ${
                      isDarkMode
                        ? 'border-gray-600 bg-gray-700 text-white'
                        : 'border-gray-300 bg-white text-gray-900'
                    }`}
                  >
                    <option value="">Select...</option>
                    {availableOrgs.map((org) => (
                      <option key={org.slug} value={org.slug}>
                        {org.name}
                      </option>
                    ))}
                  </select>
                </div>
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Role
                  </label>
                  {rolesError ? (
                    <p
                      className={`text-sm ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                    >
                      Failed to load roles
                    </p>
                  ) : (
                    <select
                      value={newRoleSlug}
                      onChange={(e) => setNewRoleSlug(e.target.value)}
                      className={`w-full rounded-md border px-3 py-2 text-sm ${
                        isDarkMode
                          ? 'border-gray-600 bg-gray-700 text-white'
                          : 'border-gray-300 bg-white text-gray-900'
                      }`}
                    >
                      <option value="">Select...</option>
                      {availableRoles.map((role) => (
                        <option key={role.slug} value={role.slug}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Button
                  onClick={() =>
                    addOrgMutation.mutate({
                      organization_slug: newOrgSlug,
                      role_slug: newRoleSlug,
                    })
                  }
                  disabled={
                    !newOrgSlug || !newRoleSlug || addOrgMutation.isPending
                  }
                  className="bg-amber-border text-white hover:bg-amber-border-strong"
                  size="sm"
                >
                  {addOrgMutation.isPending ? 'Adding...' : 'Add'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setShowAddOrg(false)
                    setNewOrgSlug('')
                    setNewRoleSlug('')
                  }}
                  className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Memberships List */}
          {(account.organizations ?? []).length > 0 ? (
            <div className="space-y-2">
              {(account.organizations ?? []).map(
                (membership: OrgMembership) => (
                  <div
                    key={membership.organization_slug}
                    className={`flex items-center justify-between rounded-lg border p-3 ${
                      isDarkMode
                        ? 'border-gray-600 bg-gray-700'
                        : 'border-gray-200 bg-gray-50'
                    }`}
                  >
                    <div className="flex-1">
                      <div
                        className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                      >
                        {membership.organization_name}
                      </div>
                      <div
                        className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                      >
                        {membership.organization_slug}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      {rolesError ? (
                        <span
                          className={`text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}
                        >
                          Roles unavailable
                        </span>
                      ) : (
                        <select
                          value={membership.role}
                          onChange={(e) =>
                            updateOrgRoleMutation.mutate({
                              orgSlug: membership.organization_slug,
                              roleSlug: e.target.value,
                            })
                          }
                          disabled={updateOrgRoleMutation.isPending}
                          aria-label={`Role for ${membership.organization_name}`}
                          className={`rounded border px-2 py-1 text-xs ${
                            isDarkMode
                              ? 'border-gray-600 bg-gray-700 text-white'
                              : 'border-gray-300 bg-white text-gray-900'
                          }`}
                        >
                          {availableRoles.map((role) => (
                            <option key={role.slug} value={role.slug}>
                              {role.name}
                            </option>
                          ))}
                        </select>
                      )}
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={`Remove from ${membership.organization_name}`}
                              onClick={() => {
                                if (
                                  confirm(
                                    `Remove ${account.display_name} from ${membership.organization_name}?`,
                                  )
                                ) {
                                  removeOrgMutation.mutate(
                                    membership.organization_slug,
                                  )
                                }
                              }}
                              disabled={removeOrgMutation.isPending}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                                  : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                              }`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Remove from organization</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  </div>
                ),
              )}
            </div>
          ) : (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <Building2
                className={`mx-auto mb-2 h-8 w-8 ${isDarkMode ? 'text-gray-600' : 'text-gray-400'}`}
              />
              <div>Not a member of any organization</div>
              <div className="mt-1 text-sm">
                This service account has no permissions until added to an
                organization
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Client Credentials */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Shield
              className={`h-5 w-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            />
            <CardTitle>Client Credentials</CardTitle>
          </div>
          <Button
            onClick={() => setShowCreateCredential(!showCreateCredential)}
            variant="outline"
            size="sm"
            className={
              isDarkMode
                ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                : ''
            }
          >
            <Plus className="mr-2 h-4 w-4" />
            Create Credential
          </Button>
        </CardHeader>
        <CardContent>
          {/* Create Credential Form */}
          {showCreateCredential && (
            <div
              className={`mb-4 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700'
                  : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="space-y-3">
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Name <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={credentialName}
                    onChange={(e) => setCredentialName(e.target.value)}
                    placeholder="e.g., production-api"
                    className={
                      isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                    }
                  />
                </div>
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Description
                  </label>
                  <Input
                    value={credentialDescription}
                    onChange={(e) => setCredentialDescription(e.target.value)}
                    placeholder="What is this credential used for?"
                    className={
                      isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                    }
                  />
                </div>
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Scopes{' '}
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                    >
                      (comma-separated)
                    </span>
                  </label>
                  <Input
                    value={credentialScopes}
                    onChange={(e) => setCredentialScopes(e.target.value)}
                    placeholder="e.g., read:projects, write:projects"
                    className={
                      isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                    }
                  />
                </div>
                <div>
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Expires in (days){' '}
                    <span
                      className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                    >
                      (leave empty for no expiration)
                    </span>
                  </label>
                  <Input
                    type="number"
                    min="1"
                    value={credentialExpiresDays}
                    onChange={(e) => setCredentialExpiresDays(e.target.value)}
                    placeholder="e.g., 90"
                    className={
                      isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''
                    }
                  />
                </div>
                <div className="flex items-center gap-2 pt-2">
                  <Button
                    onClick={handleCreateCredential}
                    disabled={
                      !credentialName.trim() ||
                      createCredentialMutation.isPending
                    }
                    className="bg-amber-border text-white hover:bg-amber-border-strong"
                  >
                    {createCredentialMutation.isPending
                      ? 'Creating...'
                      : 'Create'}
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => {
                      setShowCreateCredential(false)
                      resetCredentialForm()
                    }}
                    className={
                      isDarkMode ? 'border-gray-600 text-gray-300' : ''
                    }
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            </div>
          )}

          {/* Newly Created Credential Banner */}
          {newlyCreatedCredential && (
            <div
              className={`mb-4 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-green-700 bg-green-900/20'
                  : 'border-green-200 bg-green-50'
              }`}
            >
              <div
                className={`mb-2 font-medium ${isDarkMode ? 'text-green-400' : 'text-green-800'}`}
              >
                Client Credential Created - Copy the secret now, it will not be
                shown again!
              </div>
              <div className="space-y-2">
                <div>
                  <span
                    className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    Client ID
                  </span>
                  <div className="flex items-center gap-2">
                    <code
                      className={`flex-1 rounded border px-3 py-2 text-sm ${
                        isDarkMode
                          ? 'border-gray-600 bg-gray-800 text-green-300'
                          : 'border-gray-200 bg-white text-green-700'
                      }`}
                    >
                      {newlyCreatedCredential.client_id}
                    </code>
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            aria-label="Copy client ID"
                            onClick={() =>
                              copyToClipboard(
                                newlyCreatedCredential.client_id,
                                'cred-id',
                              )
                            }
                            className={`rounded-lg p-2 ${
                              copiedId === 'cred-id'
                                ? 'bg-green-600 text-white'
                                : isDarkMode
                                  ? 'text-gray-400 hover:bg-gray-700'
                                  : 'text-gray-600 hover:bg-gray-200'
                            }`}
                          >
                            <Copy className="h-4 w-4" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Copy to clipboard</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </div>
                <div>
                  <span
                    className={`text-xs ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    Client Secret
                  </span>
                  <div className="flex items-center gap-2">
                    <code
                      className={`flex-1 rounded border px-3 py-2 text-sm ${
                        isDarkMode
                          ? 'border-gray-600 bg-gray-800 text-green-300'
                          : 'border-gray-200 bg-white text-green-700'
                      }`}
                    >
                      {newlyCreatedCredential.client_secret}
                    </code>
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            aria-label="Copy client secret"
                            onClick={() =>
                              copyToClipboard(
                                newlyCreatedCredential.client_secret,
                                'cred-secret',
                              )
                            }
                            className={`rounded-lg p-2 ${
                              copiedId === 'cred-secret'
                                ? 'bg-green-600 text-white'
                                : isDarkMode
                                  ? 'text-gray-400 hover:bg-gray-700'
                                  : 'text-gray-600 hover:bg-gray-200'
                            }`}
                          >
                            <Copy className="h-4 w-4" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Copy to clipboard</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </div>
              </div>
              <button
                onClick={() => setNewlyCreatedCredential(null)}
                className={`mt-2 text-sm ${isDarkMode ? 'text-green-400 hover:text-green-300' : 'text-green-700 hover:text-green-800'}`}
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Credentials List */}
          {credentialsLoading ? (
            <div
              className={`py-4 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Loading client credentials...
            </div>
          ) : credentialsError ? (
            <div
              className={`flex items-center gap-2 rounded-lg p-3 ${
                isDarkMode
                  ? 'bg-red-900/20 text-red-400'
                  : 'bg-red-50 text-red-700'
              }`}
            >
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <span className="text-sm">Failed to load client credentials</span>
            </div>
          ) : credentials.length === 0 ? (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <Shield
                className={`mx-auto mb-2 h-8 w-8 ${isDarkMode ? 'text-gray-600' : 'text-gray-400'}`}
              />
              <div>No client credentials created yet</div>
              <div className="mt-1 text-sm">
                Create a credential for OAuth2 client_credentials flow
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {credentials.map((cred: ClientCredential) => (
                <div
                  key={cred.client_id}
                  className={`flex items-center justify-between rounded-lg border p-3 ${
                    cred.revoked
                      ? isDarkMode
                        ? 'border-gray-600 bg-gray-700 opacity-50'
                        : 'border-gray-200 bg-gray-50 opacity-50'
                      : isDarkMode
                        ? 'border-gray-600 bg-gray-700'
                        : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                      >
                        {cred.name}
                      </span>
                      <code
                        className={`rounded px-2 py-0.5 text-xs ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {truncateClientId(cred.client_id)}
                      </code>
                      {cred.revoked && (
                        <span
                          className={`rounded px-2 py-0.5 text-xs ${
                            isDarkMode
                              ? 'bg-red-900/30 text-red-400'
                              : 'bg-red-100 text-red-600'
                          }`}
                        >
                          Revoked
                        </span>
                      )}
                      {cred.scopes.length > 0 && cred.scopes[0] !== '*' && (
                        <span
                          className={`text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                        >
                          {cred.scopes.join(', ')}
                        </span>
                      )}
                    </div>
                    <div
                      className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Created {formatDate(cred.created_at)}
                      {cred.last_used &&
                        ` | Last used ${formatDate(cred.last_used)}`}
                      {cred.expires_at &&
                        ` | Expires ${formatDate(cred.expires_at)}`}
                    </div>
                  </div>
                  {!cred.revoked && (
                    <div className="flex items-center gap-1">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={`Rotate credential ${cred.name}`}
                              onClick={() =>
                                handleRotateCredential(cred.client_id)
                              }
                              disabled={rotateCredentialMutation.isPending}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-blue-400 hover:bg-gray-700 hover:text-blue-300'
                                  : 'text-blue-600 hover:bg-gray-100 hover:text-blue-700'
                              }`}
                            >
                              <RotateCw className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Rotate credential</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={`Revoke credential ${cred.name}`}
                              onClick={() =>
                                handleRevokeCredential(cred.client_id)
                              }
                              disabled={revokeCredentialMutation.isPending}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                                  : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                              }`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Revoke credential</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* API Keys */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Key
              className={`h-5 w-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            />
            <CardTitle>API Keys</CardTitle>
          </div>
          <Button
            onClick={() => setShowCreateKey(!showCreateKey)}
            variant="outline"
            size="sm"
            className={
              isDarkMode
                ? 'border-gray-600 text-gray-300 hover:bg-gray-700'
                : ''
            }
          >
            <Plus className="mr-2 h-4 w-4" />
            Create API Key
          </Button>
        </CardHeader>
        <CardContent>
          {/* Create Key Form */}
          {showCreateKey && (
            <div
              className={`mb-4 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-gray-600 bg-gray-700'
                  : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="flex items-end gap-3">
                <div className="flex-1">
                  <label
                    className={`mb-1.5 block text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    Key Name
                  </label>
                  <input
                    type="text"
                    value={newKeyName}
                    onChange={(e) => setNewKeyName(e.target.value)}
                    placeholder="e.g., production, staging"
                    className={`w-full rounded-lg border px-3 py-2 text-sm ${
                      isDarkMode
                        ? 'border-gray-600 bg-gray-700 text-white placeholder:text-gray-400'
                        : 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-500'
                    }`}
                  />
                </div>
                <Button
                  onClick={handleCreateKey}
                  disabled={createKeyMutation.isPending}
                  className="bg-amber-border text-white hover:bg-amber-border-strong"
                >
                  {createKeyMutation.isPending ? 'Creating...' : 'Create'}
                </Button>
                <Button
                  variant="outline"
                  onClick={() => {
                    setShowCreateKey(false)
                    setNewKeyName('')
                  }}
                  className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Newly Created Key Banner */}
          {newlyCreatedKey && (
            <div
              className={`mb-4 rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-green-700 bg-green-900/20'
                  : 'border-green-200 bg-green-50'
              }`}
            >
              <div
                className={`mb-2 font-medium ${isDarkMode ? 'text-green-400' : 'text-green-800'}`}
              >
                API Key Created - Copy it now, it will not be shown again!
              </div>
              <div className="flex items-center gap-2">
                <code
                  className={`flex-1 rounded border px-3 py-2 text-sm ${
                    isDarkMode
                      ? 'border-gray-600 bg-gray-800 text-green-300'
                      : 'border-gray-200 bg-white text-green-700'
                  }`}
                >
                  {newlyCreatedKey.key_secret}
                </code>
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        type="button"
                        aria-label="Copy API key"
                        onClick={() =>
                          copyToClipboard(newlyCreatedKey.key_secret, 'new-key')
                        }
                        className={`rounded-lg p-2 ${
                          copiedId === 'new-key'
                            ? 'bg-green-600 text-white'
                            : isDarkMode
                              ? 'text-gray-400 hover:bg-gray-700'
                              : 'text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Copy to clipboard</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
              <button
                onClick={() => setNewlyCreatedKey(null)}
                className={`mt-2 text-sm ${isDarkMode ? 'text-green-400 hover:text-green-300' : 'text-green-700 hover:text-green-800'}`}
              >
                Dismiss
              </button>
            </div>
          )}

          {/* Keys List */}
          {keysLoading ? (
            <div
              className={`py-4 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Loading API keys...
            </div>
          ) : keysError ? (
            <div
              className={`flex items-center gap-2 rounded-lg p-3 ${
                isDarkMode
                  ? 'bg-red-900/20 text-red-400'
                  : 'bg-red-50 text-red-700'
              }`}
            >
              <AlertCircle className="h-4 w-4 flex-shrink-0" />
              <span className="text-sm">Failed to load API keys</span>
            </div>
          ) : apiKeys.length === 0 ? (
            <div
              className={`py-8 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              <Key
                className={`mx-auto mb-2 h-8 w-8 ${isDarkMode ? 'text-gray-600' : 'text-gray-400'}`}
              />
              <div>No API keys created yet</div>
              <div className="mt-1 text-sm">
                Create an API key to enable programmatic access
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {apiKeys.map((key: ApiKey) => (
                <div
                  key={key.key_id}
                  className={`flex items-center justify-between rounded-lg border p-3 ${
                    key.revoked
                      ? isDarkMode
                        ? 'border-gray-600 bg-gray-700 opacity-50'
                        : 'border-gray-200 bg-gray-50 opacity-50'
                      : isDarkMode
                        ? 'border-gray-600 bg-gray-700'
                        : 'border-gray-200 bg-gray-50'
                  }`}
                >
                  <div className="flex-1">
                    <div className="flex items-center gap-2">
                      <span
                        className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                      >
                        {key.name}
                      </span>
                      <code
                        className={`rounded px-2 py-0.5 text-xs ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {key.key_id.substring(0, 7)}...
                      </code>
                      {key.revoked && (
                        <span
                          className={`rounded px-2 py-0.5 text-xs ${
                            isDarkMode
                              ? 'bg-red-900/30 text-red-400'
                              : 'bg-red-100 text-red-600'
                          }`}
                        >
                          Revoked
                        </span>
                      )}
                    </div>
                    <div
                      className={`mt-1 text-xs ${isDarkMode ? 'text-gray-500' : 'text-gray-500'}`}
                    >
                      Created {formatDate(key.created_at)}
                      {key.last_used &&
                        ` | Last used ${formatDate(key.last_used)}`}
                      {key.expires_at &&
                        ` | Expires ${formatDate(key.expires_at)}`}
                    </div>
                  </div>
                  {!key.revoked && (
                    <div className="flex items-center gap-1">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={`Rotate API key ${key.name}`}
                              onClick={() => handleRotateKey(key.key_id)}
                              disabled={rotateKeyMutation.isPending}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-blue-400 hover:bg-gray-700 hover:text-blue-300'
                                  : 'text-blue-600 hover:bg-gray-100 hover:text-blue-700'
                              }`}
                            >
                              <RotateCw className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Rotate API key</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              aria-label={`Revoke API key ${key.name}`}
                              onClick={() => handleRevokeKey(key.key_id)}
                              disabled={revokeKeyMutation.isPending}
                              className={`rounded p-1.5 ${
                                isDarkMode
                                  ? 'text-red-400 hover:bg-gray-700 hover:text-red-300'
                                  : 'text-red-600 hover:bg-gray-100 hover:text-red-700'
                              }`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Revoke API key</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Basic Information */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="space-y-0 pb-4">
          <CardTitle>Basic Information</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <Tag className="h-4 w-4" />
                Slug
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {account.slug}
              </div>
            </div>

            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Display Name
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {account.display_name}
              </div>
            </div>

            {account.description && (
              <div className="col-span-2">
                <div
                  className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Description
                </div>
                <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                  {account.description}
                </div>
              </div>
            )}

            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <Calendar className="h-4 w-4" />
                Created
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {formatDate(account.created_at)}
              </div>
            </div>

            <div>
              <div
                className={`mb-1 flex items-center gap-2 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                <Clock className="h-4 w-4" />
                Last Authenticated
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {formatDate(account.last_authenticated)}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
