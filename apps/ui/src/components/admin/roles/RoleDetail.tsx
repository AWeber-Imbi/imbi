import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Bot,
  Edit2,
  Info,
  Lock,
  Plus,
  Shield,
  Trash2,
  Users,
  UsersRound,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  getAdminSettings,
  getRole,
  getRoleGroups,
  getRoleServiceAccounts,
  getRoleUsers,
  grantPermission,
  revokePermission,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Gravatar } from '@/components/ui/gravatar'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { Permission, RoleUser, ServiceAccount } from '@/types'

type DetailTab = 'groups' | 'permissions' | 'service-accounts' | 'users'

interface RoleDetailProps {
  onBack: () => void
  onEdit: () => void
  slug: string
}

export function RoleDetail({ onBack, onEdit, slug }: RoleDetailProps) {
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<DetailTab>('permissions')
  const [showAddPermission, setShowAddPermission] = useState(false)
  const [selectedPermission, setSelectedPermission] = useState('')
  const [confirm, setConfirm] = useState<null | {
    action: 'revoke'
    permName: string
  }>(null)

  // Fetch role with permissions
  const {
    data: role,
    error,
    isLoading,
  } = useQuery({
    queryFn: ({ signal }) => getRole(slug, signal),
    queryKey: ['role', slug],
  })

  // Fetch admin settings for available permissions
  const { data: adminSettings } = useQuery({
    queryFn: ({ signal }) => getAdminSettings(signal),
    queryKey: ['adminSettings'],
  })

  // Fetch users with this role
  const {
    data: roleUsers,
    error: usersError,
    isLoading: usersLoading,
  } = useQuery({
    enabled: activeTab === 'users',
    queryFn: ({ signal }) => getRoleUsers(slug, signal),
    queryKey: ['roleUsers', slug],
  })

  // Fetch service accounts with this role
  const {
    data: roleServiceAccounts,
    error: saError,
    isLoading: saLoading,
  } = useQuery({
    enabled: activeTab === 'service-accounts',
    queryFn: ({ signal }) => getRoleServiceAccounts(slug, signal),
    queryKey: ['roleServiceAccounts', slug],
  })

  // Fetch groups with this role
  const {
    data: roleGroups,
    error: groupsError,
    isLoading: groupsLoading,
  } = useQuery({
    enabled: activeTab === 'groups',
    queryFn: ({ signal }) => getRoleGroups(slug, signal),
    queryKey: ['roleGroups', slug],
  })

  // Grant permission mutation
  const grantMutation = useMutation({
    mutationFn: (permName: string) => grantPermission(slug, permName),
    onError: (error: unknown) => {
      toast.error(`Failed to grant permission: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['role', slug] })
      setShowAddPermission(false)
      setSelectedPermission('')
    },
  })

  // Revoke permission mutation
  const revokeMutation = useMutation({
    mutationFn: (permName: string) => revokePermission(slug, permName),
    onError: (error: unknown) => {
      toast.error(
        `Failed to revoke permission: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['role', slug] })
    },
  })

  // Available permissions not already assigned
  const assignedPermNames = new Set(role?.permissions?.map((p) => p.name) || [])
  const availablePermissions = (adminSettings?.permissions || []).filter(
    (p) => !assignedPermNames.has(p.name),
  )

  const handleGrantPermission = () => {
    if (selectedPermission) {
      grantMutation.mutate(selectedPermission)
    }
  }

  const handleRevokePermission = (permName: string) => {
    setConfirm({ action: 'revoke', permName })
  }

  // Group permissions by resource type
  const groupedPermissions = (role?.permissions || []).reduce<
    Record<string, Permission[]>
  >((acc, perm) => {
    const key = perm.resource_type
    if (!acc[key]) acc[key] = []
    acc[key].push(perm)
    return acc
  }, {})

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-sm text-secondary">Loading role...</div>
      </div>
    )
  }

  if (error || !role) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load role</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'Role not found'}
          </div>
        </div>
      </div>
    )
  }

  const tabs: { icon: typeof Shield; id: DetailTab; label: string }[] = [
    { icon: Shield, id: 'permissions', label: 'Permissions' },
    { icon: Users, id: 'users', label: 'Users' },
    { icon: Bot, id: 'service-accounts', label: 'Service Accounts' },
    { icon: UsersRound, id: 'groups', label: 'Groups' },
  ]

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Role info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="rounded-lg bg-info p-2">
              <Shield className="h-6 w-6 text-info" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <CardTitle>{role.name}</CardTitle>
                {role.is_system && (
                  <Badge className="gap-1" variant="warning">
                    <Lock className="h-3 w-3" />
                    System
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-secondary">
                {role.description || 'No description'}
              </p>
            </div>
          </div>
          {!role.is_system && (
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              onClick={onEdit}
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit Role
            </Button>
          )}
        </CardHeader>

        {/* Stats Bar */}
        <div
          className={
            'flex items-center gap-6 border-b border-tertiary px-6 py-4'
          }
        >
          <div>
            <div className="text-xs text-secondary">Slug</div>
            <div className="font-mono text-sm text-primary">{role.slug}</div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Priority</div>
            <div className="text-sm text-primary">{role.priority}</div>
          </div>
          <div className="h-8 border-l border-tertiary" />
          <div>
            <div className="text-xs text-secondary">Permissions</div>
            <div className="text-sm text-primary">
              {role.permissions?.length || 0}
            </div>
          </div>
          {role.parent_role && (
            <>
              <div className="h-8 border-l border-tertiary" />
              <div>
                <div className="text-xs text-secondary">Inherits From</div>
                <div className="text-sm text-primary">
                  {role.parent_role.name}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Tabs */}
        <div className="border-b border-tertiary">
          <div className="flex gap-0 px-6">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                    isActive
                      ? 'border-info text-info'
                      : 'border-transparent text-secondary hover:text-primary'
                  }`}
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon className="h-4 w-4" />
                  {tab.label}
                </button>
              )
            })}
          </div>
        </div>
      </Card>

      {/* Permissions Tab */}
      {activeTab === 'permissions' && (
        <div className="space-y-4">
          {/* Add Permission Section */}
          {!role.is_system && (
            <div className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-medium text-primary">
                  Assign Permission
                </h3>
                <button
                  className="hover:text-info/80 text-sm text-info"
                  onClick={() => setShowAddPermission(!showAddPermission)}
                >
                  {showAddPermission ? 'Cancel' : 'Add Permission'}
                </button>
              </div>

              {showAddPermission && (
                <div className="flex items-center gap-2">
                  <select
                    className="flex-1 rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground"
                    onChange={(e) => setSelectedPermission(e.target.value)}
                    value={selectedPermission}
                  >
                    <option value="">Select a permission...</option>
                    {availablePermissions.map((perm) => (
                      <option key={perm.name} value={perm.name}>
                        {perm.name} - {perm.description || perm.action}
                      </option>
                    ))}
                  </select>
                  <Button
                    className="bg-action text-action-foreground hover:bg-action-hover"
                    disabled={!selectedPermission || grantMutation.isPending}
                    onClick={handleGrantPermission}
                    size="sm"
                  >
                    <Plus className="mr-2 h-4 w-4" />
                    {grantMutation.isPending ? 'Adding...' : 'Assign'}
                  </Button>
                </div>
              )}

              <div className="mt-3 flex items-start gap-2 rounded bg-info p-2 text-xs text-info">
                <AlertCircle className="mt-0.5 h-3 w-3 flex-shrink-0" />
                <span>
                  Permissions define what actions users with this role can
                  perform
                </span>
              </div>
            </div>
          )}

          {/* Permissions Table */}
          {Object.keys(groupedPermissions).length === 0 ? (
            <div className="py-8 text-center text-tertiary">
              <Shield className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No permissions assigned</div>
              {!role.is_system && (
                <div className="mt-1 text-sm">
                  Use the section above to add permissions
                </div>
              )}
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <Table>
                  <TableHeader className="border-b border-tertiary bg-secondary">
                    <TableRow>
                      <TableHead className="px-6 py-3 text-left text-xs uppercase tracking-wider text-tertiary">
                        Permission
                      </TableHead>
                      <TableHead className="px-6 py-3 text-left text-xs uppercase tracking-wider text-tertiary">
                        Description
                      </TableHead>
                      {!role.is_system && (
                        <TableHead className="px-6 py-3 text-right text-xs uppercase tracking-wider text-tertiary">
                          Actions
                        </TableHead>
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody className="divide-y divide-tertiary">
                    {(role.permissions || [])
                      .sort((a, b) => a.name.localeCompare(b.name))
                      .map((perm) => (
                        <TableRow
                          className="hover:bg-secondary"
                          key={perm.name}
                        >
                          <TableCell className="px-6 py-4 text-primary">
                            <code className="rounded bg-secondary px-2 py-1 text-sm text-info">
                              {perm.name}
                            </code>
                          </TableCell>
                          <TableCell className="px-6 py-4 text-sm text-secondary">
                            {perm.description || perm.action}
                          </TableCell>
                          {!role.is_system && (
                            <TableCell className="px-6 py-4 text-right">
                              <TooltipProvider delayDuration={200}>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <button
                                      className="rounded p-1.5 text-danger hover:bg-danger"
                                      disabled={revokeMutation.isPending}
                                      onClick={() =>
                                        handleRevokePermission(perm.name)
                                      }
                                    >
                                      <Trash2 className="h-4 w-4" />
                                    </button>
                                  </TooltipTrigger>
                                  <TooltipContent>
                                    <p>Remove permission</p>
                                  </TooltipContent>
                                </Tooltip>
                              </TooltipProvider>
                            </TableCell>
                          )}
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Users Tab */}
      {activeTab === 'users' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className="flex items-start gap-3 rounded-lg border border-tertiary bg-card p-4 dark:border-border dark:bg-card">
            <Info className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
            <div className="text-sm text-info">
              Role assignments are managed via User Management. This list shows
              users directly assigned this role.
            </div>
          </div>

          {/* User list */}
          {usersLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-sm text-secondary">Loading users...</div>
            </div>
          ) : usersError ? (
            <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div>
                <div className="font-medium">Failed to load users</div>
                <div className="mt-1 text-sm">
                  {usersError instanceof Error
                    ? usersError.message
                    : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !roleUsers || roleUsers.length === 0 ? (
            <div className="py-8 text-center text-tertiary">
              <Users className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No users directly assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to users via User Management
              </div>
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <div className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-border bg-secondary px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-tertiary">
                  <div>User</div>
                  <div>Status</div>
                  <div>Last Login</div>
                </div>
                <div className="divide-y divide-tertiary">
                  {roleUsers.map((user: RoleUser) => (
                    <div
                      className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-3"
                      key={user.email}
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <Gravatar
                          className="flex-shrink-0 rounded-full"
                          email={user.email}
                          size={32}
                        />
                        <div className="min-w-0">
                          <div
                            className={
                              'truncate text-sm font-medium text-primary'
                            }
                          >
                            {user.display_name}
                          </div>
                          <div className="truncate text-xs text-tertiary">
                            {user.email}
                          </div>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        {user.is_active ? (
                          <Badge variant="success">Active</Badge>
                        ) : (
                          <Badge variant="neutral">Inactive</Badge>
                        )}
                        {user.is_service_account && (
                          <Badge variant="accent">Service</Badge>
                        )}
                      </div>
                      <div className="text-sm text-tertiary">
                        {user.last_login
                          ? new Date(user.last_login).toLocaleDateString()
                          : 'Never'}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Service Accounts Tab */}
      {activeTab === 'service-accounts' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className="flex items-start gap-3 rounded-lg border border-tertiary bg-card p-4 dark:border-border dark:bg-card">
            <Info className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
            <div className="text-sm text-info">
              Role assignments are managed via Service Account Management. This
              list shows service accounts assigned this role via organization
              membership.
            </div>
          </div>

          {/* Service account list */}
          {saLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-sm text-secondary">
                Loading service accounts...
              </div>
            </div>
          ) : saError ? (
            <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div>
                <div className="font-medium">
                  Failed to load service accounts
                </div>
                <div className="mt-1 text-sm">
                  {saError instanceof Error
                    ? saError.message
                    : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !roleServiceAccounts || roleServiceAccounts.length === 0 ? (
            <div className="py-8 text-center text-tertiary">
              <Bot className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No service accounts assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to service accounts via Service Account
                Management
              </div>
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <div className="grid grid-cols-[1fr_auto_auto] gap-4 border-b border-border bg-secondary px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-tertiary">
                  <div>Service Account</div>
                  <div>Status</div>
                  <div>Last Authenticated</div>
                </div>
                <div className="divide-y divide-tertiary">
                  {roleServiceAccounts.map((sa: ServiceAccount) => (
                    <div
                      className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-3"
                      key={sa.slug}
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <div
                          className={
                            'rounded-full bg-purple-100 p-1.5 dark:bg-purple-900/30'
                          }
                        >
                          <Bot
                            className={
                              'h-4 w-4 text-purple-600 dark:text-purple-400'
                            }
                          />
                        </div>
                        <div className="min-w-0">
                          <div
                            className={
                              'truncate text-sm font-medium text-primary'
                            }
                          >
                            {sa.display_name}
                          </div>
                          <div
                            className={
                              'truncate font-mono text-xs text-tertiary'
                            }
                          >
                            {sa.slug}
                          </div>
                        </div>
                      </div>
                      <div>
                        {sa.is_active ? (
                          <Badge variant="success">Active</Badge>
                        ) : (
                          <Badge variant="neutral">Inactive</Badge>
                        )}
                      </div>
                      <div className="text-sm text-tertiary">
                        {sa.last_authenticated
                          ? new Date(sa.last_authenticated).toLocaleDateString()
                          : 'Never'}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Groups Tab */}
      {activeTab === 'groups' && (
        <div className="space-y-4">
          {/* Info banner */}
          <div className="flex items-start gap-3 rounded-lg border border-tertiary bg-card p-4 dark:border-border dark:bg-card">
            <Info className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
            <div className="text-sm text-info">
              Role assignments to teams are managed via Team Management. All
              members of a team inherit the team's roles.
            </div>
          </div>

          {/* Group list */}
          {groupsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-sm text-secondary">Loading groups...</div>
            </div>
          ) : groupsError ? (
            <div className="flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger">
              <AlertCircle className="h-5 w-5 flex-shrink-0" />
              <div>
                <div className="font-medium">Failed to load groups</div>
                <div className="mt-1 text-sm">
                  {groupsError instanceof Error
                    ? groupsError.message
                    : 'An error occurred'}
                </div>
              </div>
            </div>
          ) : !roleGroups || roleGroups.length === 0 ? (
            <div className="py-8 text-center text-tertiary">
              <UsersRound className="mx-auto mb-2 h-8 w-8 opacity-50" />
              <div>No groups assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to teams via Team Management
              </div>
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <div className="grid grid-cols-[1fr_1fr] gap-4 border-b border-border bg-secondary px-4 py-2.5 text-xs font-medium uppercase tracking-wider text-tertiary">
                  <div>Group</div>
                  <div>Description</div>
                </div>
                <div className="divide-y divide-tertiary">
                  {roleGroups.map(
                    (group: {
                      description?: null | string
                      name: string
                      slug: string
                    }) => (
                      <div
                        className="grid grid-cols-[1fr_1fr] items-center gap-4 px-4 py-3"
                        key={group.slug}
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <div className="rounded bg-secondary p-1.5">
                            <UsersRound className="h-4 w-4 text-secondary" />
                          </div>
                          <div className="min-w-0">
                            <div
                              className={
                                'truncate text-sm font-medium text-primary'
                              }
                            >
                              {group.name}
                            </div>
                            <div
                              className={
                                'truncate font-mono text-xs text-tertiary'
                              }
                            >
                              {group.slug}
                            </div>
                          </div>
                        </div>
                        <div className="truncate text-sm text-tertiary">
                          {group.description || 'No description'}
                        </div>
                      </div>
                    ),
                  )}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}
      <ConfirmDialog
        confirmLabel="Remove"
        description={
          confirm?.action === 'revoke'
            ? `Remove permission "${confirm.permName}" from this role?`
            : 'This action cannot be undone.'
        }
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'revoke') {
            revokeMutation.mutate(confirm.permName)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'revoke'}
        title="Remove permission"
      />
    </div>
  )
}
