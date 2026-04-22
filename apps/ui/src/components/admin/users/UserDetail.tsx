import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { extractApiErrorDetail } from '@/lib/apiError'
import {
  ArrowLeft,
  Edit2,
  Power,
  Clock,
  User,
  Mail,
  Calendar,
  Shield,
  Plus,
  Trash2,
  Building2,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Gravatar } from '@/components/ui/gravatar'
import {
  getRoles,
  addUserToOrg,
  updateUserOrgRole,
  removeUserFromOrg,
} from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { AdminUser, OrgMembership } from '@/types'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface UserDetailProps {
  user: AdminUser
  onEdit: () => void
  onBack: () => void
}

export function UserDetail({ user, onEdit, onBack }: UserDetailProps) {
  const queryClient = useQueryClient()
  const { organizations: allOrgs } = useOrganization()
  const [showAddOrg, setShowAddOrg] = useState(false)
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newRoleSlug, setNewRoleSlug] = useState('')
  const [confirm, setConfirm] = useState<{
    action: 'remove-org'
    orgSlug: string
    orgName: string
  } | null>(null)

  const { data: availableRoles = [] } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  const addOrgMutation = useMutation({
    mutationFn: (data: { organization_slug: string; role_slug: string }) =>
      addUserToOrg(user.email, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
      setShowAddOrg(false)
      setNewOrgSlug('')
      setNewRoleSlug('')
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to add to organization: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  const updateRoleMutation = useMutation({
    mutationFn: ({
      orgSlug,
      roleSlug,
    }: {
      orgSlug: string
      roleSlug: string
    }) => updateUserOrgRole(user.email, orgSlug, { role_slug: roleSlug }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
    },
    onError: (error: unknown) => {
      toast.error(`Failed to update role: ${extractApiErrorDetail(error)}`)
    },
  })

  const removeOrgMutation = useMutation({
    mutationFn: (orgSlug: string) => removeUserFromOrg(user.email, orgSlug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['adminUsers'] })
      queryClient.invalidateQueries({ queryKey: ['adminUser', user.email] })
    },
    onError: (error: unknown) => {
      toast.error(
        `Failed to remove from organization: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  // Orgs the user is not already a member of
  const memberOrgSlugs = new Set(
    (user.organizations ?? []).map((o) => o.organization_slug),
  )
  const availableOrgs = allOrgs.filter((o) => !memberOrgSlugs.has(o.slug))

  const formatDate = (dateString?: string | null) => {
    if (!dateString) return 'Never'
    return new Date(dateString).toLocaleString('en-US', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button variant="outline" onClick={onBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* User info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            <Gravatar
              email={user.email}
              size={48}
              alt={user.display_name}
              className="h-12 w-12 rounded-full"
            />
            <div>
              <CardTitle>{user.display_name}</CardTitle>
              <p className="mt-1 text-secondary">{user.email}</p>
            </div>
          </div>
          <Button
            onClick={onEdit}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit User
          </Button>
        </CardHeader>

        {/* Account Status */}
        <div className="border-b border-tertiary px-6 py-5">
          <div className="flex items-center gap-6">
            <div
              className={`flex items-center gap-2 rounded px-3 py-1.5 ${
                user.is_active
                  ? 'bg-success text-success'
                  : 'bg-secondary text-secondary'
              }`}
            >
              <Power className="h-4 w-4" />
              {user.is_active ? 'Active' : 'Inactive'}
            </div>
            {user.is_admin && (
              <div className="flex items-center gap-2 rounded bg-danger px-3 py-1.5 text-danger">
                <Shield className="h-4 w-4" />
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
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <Mail className="h-4 w-4" />
                Email
              </div>
              <div className="text-primary">{user.email}</div>
            </div>

            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <User className="h-4 w-4" />
                Display Name
              </div>
              <div className="text-primary">{user.display_name}</div>
            </div>

            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <Calendar className="h-4 w-4" />
                Created
              </div>
              <div className="text-primary">{formatDate(user.created_at)}</div>
            </div>

            <div>
              <div
                className={
                  'mb-1 flex items-center gap-2 text-sm text-secondary'
                }
              >
                <Clock className="h-4 w-4" />
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
            <Building2 className="h-5 w-5 text-secondary" />
            <CardTitle>Organization Memberships</CardTitle>
          </div>
          {availableOrgs.length > 0 && (
            <Button
              onClick={() => setShowAddOrg(!showAddOrg)}
              variant="outline"
              size="sm"
              className=""
            >
              <Plus className="mr-2 h-4 w-4" />
              Add to Organization
            </Button>
          )}
        </CardHeader>
        <CardContent>
          {/* Add to Organization Form */}
          {showAddOrg && (
            <div className="mb-4 rounded-lg border border-input bg-secondary p-4">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="mb-1.5 block text-sm text-secondary">
                    Organization
                  </label>
                  <select
                    value={newOrgSlug}
                    onChange={(e) => setNewOrgSlug(e.target.value)}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
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
                  <label className="mb-1.5 block text-sm text-secondary">
                    Role
                  </label>
                  <select
                    value={newRoleSlug}
                    onChange={(e) => setNewRoleSlug(e.target.value)}
                    className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
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
                  onClick={() =>
                    addOrgMutation.mutate({
                      organization_slug: newOrgSlug,
                      role_slug: newRoleSlug,
                    })
                  }
                  disabled={
                    !newOrgSlug || !newRoleSlug || addOrgMutation.isPending
                  }
                  className="bg-action text-action-foreground hover:bg-action-hover"
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
                  key={membership.organization_slug}
                  className="flex items-center justify-between rounded-lg border border-input bg-secondary p-3"
                >
                  <div className="flex-1">
                    <div className="text-sm font-medium text-primary">
                      {membership.organization_name}
                    </div>
                    <div className="text-xs text-tertiary">
                      {membership.organization_slug}
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={membership.role}
                      onChange={(e) =>
                        updateRoleMutation.mutate({
                          orgSlug: membership.organization_slug,
                          roleSlug: e.target.value,
                        })
                      }
                      disabled={updateRoleMutation.isPending}
                      className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
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
                            onClick={() =>
                              setConfirm({
                                action: 'remove-org',
                                orgSlug: membership.organization_slug,
                                orgName: membership.organization_name,
                              })
                            }
                            disabled={removeOrgMutation.isPending}
                            className="rounded p-1.5 text-danger hover:bg-secondary"
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
              ))}
            </div>
          ) : (
            <div className="py-8 text-center text-tertiary">
              <Building2 className="mx-auto mb-2 h-8 w-8 text-tertiary" />
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
          <div className="py-8 text-center text-tertiary">
            <div>0 active sessions</div>
            <div className="mt-1 text-sm">
              No JWT tokens currently active for this user
            </div>
          </div>
        </CardContent>
      </Card>
      <ConfirmDialog
        open={confirm?.action === 'remove-org'}
        title="Remove from organization"
        description={
          confirm?.action === 'remove-org'
            ? `Remove ${user.display_name} from ${confirm.orgName}?`
            : 'This action cannot be undone.'
        }
        confirmLabel="Remove"
        onConfirm={() => {
          if (confirm?.action === 'remove-org') {
            removeOrgMutation.mutate(confirm.orgSlug)
          }
          setConfirm(null)
        }}
        onCancel={() => setConfirm(null)}
      />
    </div>
  )
}
