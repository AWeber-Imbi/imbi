import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Building2,
  Calendar,
  Clock,
  Edit2,
  Mail,
  Plus,
  Power,
  Shield,
  Trash2,
  User,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  addUserToOrg,
  getRoles,
  removeUserFromOrg,
  updateUserOrgRole,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Gravatar } from '@/components/ui/gravatar'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildReplacePatch } from '@/lib/json-patch'
import type { AdminUser, OrgMembership } from '@/types'

interface UserDetailProps {
  onBack: () => void
  onEdit: () => void
  user: AdminUser
}

export function UserDetail({ onBack, onEdit, user }: UserDetailProps) {
  const queryClient = useQueryClient()
  const { organizations: allOrgs } = useOrganization()
  const [showAddOrg, setShowAddOrg] = useState(false)
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newRoleSlug, setNewRoleSlug] = useState('')
  const [confirm, setConfirm] = useState<null | {
    action: 'remove-org'
    orgName: string
    orgSlug: string
  }>(null)

  const { data: availableRoles = [] } = useQuery({
    queryFn: ({ signal }) => getRoles(signal),
    queryKey: ['roles'],
  })

  const addOrgMutation = useMutation({
    mutationFn: (data: { organization_slug: string; role_slug: string }) =>
      addUserToOrg(user.email, data),
    onError: (error: unknown) => {
      toast.error(
        `Failed to add to organization: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
      setShowAddOrg(false)
      setNewOrgSlug('')
      setNewRoleSlug('')
    },
  })

  const updateRoleMutation = useMutation({
    mutationFn: ({
      orgSlug,
      roleSlug,
    }: {
      orgSlug: string
      roleSlug: string
    }) =>
      updateUserOrgRole(
        user.email,
        orgSlug,
        buildReplacePatch({ role_slug: roleSlug }),
      ),
    onError: (error: unknown) => {
      toast.error(`Failed to update role: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
    },
  })

  const removeOrgMutation = useMutation({
    mutationFn: (orgSlug: string) => removeUserFromOrg(user.email, orgSlug),
    onError: (error: unknown) => {
      toast.error(
        `Failed to remove from organization: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
    },
  })

  // Orgs the user is not already a member of
  const memberOrgSlugs = new Set(
    (user.organizations ?? []).map((o) => o.organization_slug),
  )
  const availableOrgs = allOrgs.filter((o) => !memberOrgSlugs.has(o.slug))

  const formatDate = (dateString?: null | string) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      month: 'long',
      year: 'numeric',
    })
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 size-4" />
          Back
        </Button>
      </div>

      {/* User info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            <Gravatar
              alt={user.display_name}
              className="size-12 rounded-full"
              email={user.email}
              size={48}
            />
            <div>
              <CardTitle>{user.display_name}</CardTitle>
              <p className="text-secondary mt-1">{user.email}</p>
            </div>
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 size-4" />
            Edit User
          </Button>
        </CardHeader>

        {/* Account Status */}
        <div className="border-tertiary border-b px-6 py-5">
          <div className="flex items-center gap-6">
            <div
              className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                user.is_active
                  ? 'bg-success text-success'
                  : 'bg-secondary text-secondary'
              }`}
            >
              <Power className="size-4" />
              {user.is_active ? 'Active' : 'Inactive'}
            </div>
            {user.is_admin && (
              <div className="bg-danger text-danger flex items-center gap-2 rounded px-3 py-1.5">
                <Shield className="size-4" />
                Administrator
              </div>
            )}
            {user.is_service_account && (
              <div className="flex items-center gap-2 rounded bg-purple-100 px-3 py-1.5 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
                Service Account
              </div>
            )}
          </div>
        </div>

        {/* Basic Information */}
        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div
                className={
                  'text-secondary mb-1 flex items-center gap-2 text-sm'
                }
              >
                <Mail className="size-4" />
                Email
              </div>
              <div className="text-primary">{user.email}</div>
            </div>

            <div>
              <div
                className={
                  'text-secondary mb-1 flex items-center gap-2 text-sm'
                }
              >
                <User className="size-4" />
                Display Name
              </div>
              <div className="text-primary">{user.display_name}</div>
            </div>

            <div>
              <div
                className={
                  'text-secondary mb-1 flex items-center gap-2 text-sm'
                }
              >
                <Calendar className="size-4" />
                Created
              </div>
              <div className="text-primary">{formatDate(user.created_at)}</div>
            </div>

            <div>
              <div
                className={
                  'text-secondary mb-1 flex items-center gap-2 text-sm'
                }
              >
                <Clock className="size-4" />
                Last Login
              </div>
              <div className="text-primary">{formatDate(user.last_login)}</div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Organization Memberships */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
          <div className="flex items-center gap-2">
            <Building2 className="text-secondary size-5" />
            <CardTitle>Organization Memberships</CardTitle>
          </div>
          {availableOrgs.length > 0 && (
            <Button
              className=""
              onClick={() => setShowAddOrg(!showAddOrg)}
              size="sm"
              variant="outline"
            >
              <Plus className="mr-2 size-4" />
              Add to Organization
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {/* Add to Organization Form */}
          {showAddOrg && (
            <div className="border-input bg-secondary mb-4 rounded-lg border p-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-secondary mb-1.5 block text-sm">
                    Organization
                  </label>
                  <select
                    className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 text-sm"
                    onChange={(e) => setNewOrgSlug(e.target.value)}
                    value={newOrgSlug}
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
                  <label className="text-secondary mb-1.5 block text-sm">
                    Role
                  </label>
                  <select
                    className="border-input bg-background text-foreground w-full rounded-md border px-3 py-2 text-sm"
                    onChange={(e) => setNewRoleSlug(e.target.value)}
                    value={newRoleSlug}
                  >
                    <option value="">Select...</option>
                    {availableRoles.map((role) => (
                      <option key={role.slug} value={role.slug}>
                        {role.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
              <div className="mt-3 flex items-center gap-2">
                <Button
                  className="bg-action text-action-foreground hover:bg-action-hover"
                  disabled={
                    !newOrgSlug || !newRoleSlug || addOrgMutation.isPending
                  }
                  onClick={() =>
                    addOrgMutation.mutate({
                      organization_slug: newOrgSlug,
                      role_slug: newRoleSlug,
                    })
                  }
                  size="sm"
                >
                  {addOrgMutation.isPending ? 'Adding...' : 'Add'}
                </Button>
                <Button
                  onClick={() => {
                    setShowAddOrg(false)
                    setNewOrgSlug('')
                    setNewRoleSlug('')
                  }}
                  size="sm"
                  variant="outline"
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}

          {/* Memberships List */}
          {(user.organizations ?? []).length > 0 ? (
            <div className="space-y-2">
              {(user.organizations ?? []).map((membership: OrgMembership) => (
                <div
                  className="border-input bg-secondary flex items-center justify-between rounded-lg border p-3"
                  key={membership.organization_slug}
                >
                  <div className="flex-1">
                    <div className="text-primary text-sm font-medium">
                      {membership.organization_name}
                    </div>
                    <div className="text-tertiary text-xs">
                      {membership.organization_slug}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      className="border-input bg-background text-foreground rounded border px-2 py-1 text-xs"
                      disabled={updateRoleMutation.isPending}
                      onChange={(e) =>
                        updateRoleMutation.mutate({
                          orgSlug: membership.organization_slug,
                          roleSlug: e.target.value,
                        })
                      }
                      value={membership.role}
                    >
                      {availableRoles.map((role) => (
                        <option key={role.slug} value={role.slug}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                    <TooltipProvider delayDuration={200}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            className="text-danger hover:bg-secondary rounded p-1.5"
                            disabled={removeOrgMutation.isPending}
                            onClick={() =>
                              setConfirm({
                                action: 'remove-org',
                                orgName: membership.organization_name,
                                orgSlug: membership.organization_slug,
                              })
                            }
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent>
                          <p>Remove from organization</p>
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-tertiary py-8 text-center">
              <Building2 className="text-tertiary mx-auto mb-2 size-8" />
              <div>Not a member of any organization</div>
              <div className="mt-1 text-sm">
                This user has no permissions until added to an organization
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Active Sessions */}
      <Card>
        <CardHeader className="pb-4">
          <CardTitle>Active Sessions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-tertiary py-8 text-center">
            <div>0 active sessions</div>
            <div className="mt-1 text-sm">
              No JWT tokens currently active for this user
            </div>
          </div>
        </CardContent>
      </Card>
      <ConfirmDialog
        confirmLabel="Remove"
        description={
          confirm?.action === 'remove-org'
            ? `Remove ${user.display_name} from ${confirm.orgName}?`
            : 'This action cannot be undone.'
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'remove-org') {
            removeOrgMutation.mutate(confirm.orgSlug)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'remove-org'}
        title="Remove from organization"
      />
    </div>
  )
}
