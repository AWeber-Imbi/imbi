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
        <div className="text-secondary text-sm">Loading role...</div>
      </div>
    )
  }

  if (error || !role) {
    return (
      <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
        <AlertCircle className="size-5 shrink-0" />
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
          <ArrowLeft className="mr-2 size-4" />
          Back
        </Button>
      </div>

      {/* Role info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            <div className="bg-info rounded-lg p-2">
              <Shield className="text-info size-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <CardTitle>{role.name}</CardTitle>
                {role.is_system && (
                  <Badge className="gap-1" variant="warning">
                    <Lock className="size-3" />
                    System
                  </Badge>
                )}
              </div>
              <p className="text-secondary mt-1">
                {role.description || 'No description'}
              </p>
            </div>
          </div>
          {!role.is_system && (
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              onClick={onEdit}
            >
              <Edit2 className="mr-2 size-4" />
              Edit Role
            </Button>
          )}
        </CardHeader>

        {/* Stats Bar */}
        <div
          className={
            'border-tertiary flex items-center gap-6 border-b px-6 py-4'
          }
        >
          <div>
            <div className="text-secondary text-xs">Slug</div>
            <div className="text-primary font-mono text-sm">{role.slug}</div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Priority</div>
            <div className="text-primary text-sm">{role.priority}</div>
          </div>
          <div className="border-tertiary h-8 border-l" />
          <div>
            <div className="text-secondary text-xs">Permissions</div>
            <div className="text-primary text-sm">
              {role.permissions?.length || 0}
            </div>
          </div>
          {role.parent_role && (
            <>
              <div className="border-tertiary h-8 border-l" />
              <div>
                <div className="text-secondary text-xs">Inherits From</div>
                <div className="text-primary text-sm">
                  {role.parent_role.name}
                </div>
              </div>
            </>
          )}
        </div>

        {/* Tabs */}
        <div className="border-tertiary border-b">
          <div className="flex gap-0 px-6">
            {tabs.map((tab) => {
              const Icon = tab.icon
              const isActive = activeTab === tab.id
              return (
                <button
                  className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                    isActive
                      ? 'border-info text-info'
                      : 'text-secondary hover:text-primary border-transparent'
                  }`}
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                >
                  <Icon className="size-4" />
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
            <div className="border-border bg-card rounded-lg border p-4">
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-primary text-sm font-medium">
                  Assign Permission
                </h3>
                <button
                  className="text-info hover:text-info/80 text-sm"
                  onClick={() => setShowAddPermission(!showAddPermission)}
                >
                  {showAddPermission ? 'Cancel' : 'Add Permission'}
                </button>
              </div>

              {showAddPermission && (
                <div className="flex items-center gap-2">
                  <select
                    className="border-input bg-background text-foreground flex-1 rounded-lg border px-3 py-2 text-sm"
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
                    <Plus className="mr-2 size-4" />
                    {grantMutation.isPending ? 'Adding...' : 'Assign'}
                  </Button>
                </div>
              )}

              <div className="bg-info text-info mt-3 flex items-start gap-2 rounded p-2 text-xs">
                <AlertCircle className="mt-0.5 size-3 shrink-0" />
                <span>
                  Permissions define what actions users with this role can
                  perform
                </span>
              </div>
            </div>
          )}

          {/* Permissions Table */}
          {Object.keys(groupedPermissions).length === 0 ? (
            <div className="text-tertiary py-8 text-center">
              <Shield className="mx-auto mb-2 size-8 opacity-50" />
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
                  <TableHeader className="border-tertiary bg-secondary border-b">
                    <TableRow>
                      <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                        Permission
                      </TableHead>
                      <TableHead className="text-tertiary px-6 py-3 text-left text-xs tracking-wider uppercase">
                        Description
                      </TableHead>
                      {!role.is_system && (
                        <TableHead className="text-tertiary px-6 py-3 text-right text-xs tracking-wider uppercase">
                          Actions
                        </TableHead>
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody className="divide-tertiary divide-y">
                    {(role.permissions || [])
                      .sort((a, b) => a.name.localeCompare(b.name))
                      .map((perm) => (
                        <TableRow
                          className="hover:bg-secondary"
                          key={perm.name}
                        >
                          <TableCell className="text-primary px-6 py-4">
                            <code className="bg-secondary text-info rounded px-2 py-1 text-sm">
                              {perm.name}
                            </code>
                          </TableCell>
                          <TableCell className="text-secondary px-6 py-4 text-sm">
                            {perm.description || perm.action}
                          </TableCell>
                          {!role.is_system && (
                            <TableCell className="px-6 py-4 text-right">
                              <TooltipProvider delayDuration={200}>
                                <Tooltip>
                                  <TooltipTrigger asChild>
                                    <button
                                      className="text-danger hover:bg-danger rounded p-1.5"
                                      disabled={revokeMutation.isPending}
                                      onClick={() =>
                                        handleRevokePermission(perm.name)
                                      }
                                    >
                                      <Trash2 className="size-4" />
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
          <div className="border-tertiary bg-card dark:border-border dark:bg-card flex items-start gap-3 rounded-lg border p-4">
            <Info className="text-info mt-0.5 size-5 shrink-0" />
            <div className="text-info text-sm">
              Role assignments are managed via User Management. This list shows
              users directly assigned this role.
            </div>
          </div>

          {/* User list */}
          {usersLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-secondary text-sm">Loading users...</div>
            </div>
          ) : usersError ? (
            <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
              <AlertCircle className="size-5 shrink-0" />
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
            <div className="text-tertiary py-8 text-center">
              <Users className="mx-auto mb-2 size-8 opacity-50" />
              <div>No users directly assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to users via User Management
              </div>
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <div className="border-border bg-secondary text-tertiary grid grid-cols-[1fr_auto_auto] gap-4 border-b px-4 py-2.5 text-xs font-medium tracking-wider uppercase">
                  <div>User</div>
                  <div>Status</div>
                  <div>Last Login</div>
                </div>
                <div className="divide-tertiary divide-y">
                  {roleUsers.map((user: RoleUser) => (
                    <div
                      className="grid grid-cols-[1fr_auto_auto] items-center gap-4 px-4 py-3"
                      key={user.email}
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <Gravatar
                          className="shrink-0 rounded-full"
                          email={user.email}
                          size={32}
                        />
                        <div className="min-w-0">
                          <div
                            className={
                              'text-primary truncate text-sm font-medium'
                            }
                          >
                            {user.display_name}
                          </div>
                          <div className="text-tertiary truncate text-xs">
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
                      <div className="text-tertiary text-sm">
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
          <div className="border-tertiary bg-card dark:border-border dark:bg-card flex items-start gap-3 rounded-lg border p-4">
            <Info className="text-info mt-0.5 size-5 shrink-0" />
            <div className="text-info text-sm">
              Role assignments are managed via Service Account Management. This
              list shows service accounts assigned this role via organization
              membership.
            </div>
          </div>

          {/* Service account list */}
          {saLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-secondary text-sm">
                Loading service accounts...
              </div>
            </div>
          ) : saError ? (
            <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
              <AlertCircle className="size-5 shrink-0" />
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
            <div className="text-tertiary py-8 text-center">
              <Bot className="mx-auto mb-2 size-8 opacity-50" />
              <div>No service accounts assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to service accounts via Service Account
                Management
              </div>
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <div className="border-border bg-secondary text-tertiary grid grid-cols-[1fr_auto_auto] gap-4 border-b px-4 py-2.5 text-xs font-medium tracking-wider uppercase">
                  <div>Service Account</div>
                  <div>Status</div>
                  <div>Last Authenticated</div>
                </div>
                <div className="divide-tertiary divide-y">
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
                              'size-4 text-purple-600 dark:text-purple-400'
                            }
                          />
                        </div>
                        <div className="min-w-0">
                          <div
                            className={
                              'text-primary truncate text-sm font-medium'
                            }
                          >
                            {sa.display_name}
                          </div>
                          <div
                            className={
                              'text-tertiary truncate font-mono text-xs'
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
                      <div className="text-tertiary text-sm">
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
          <div className="border-tertiary bg-card dark:border-border dark:bg-card flex items-start gap-3 rounded-lg border p-4">
            <Info className="text-info mt-0.5 size-5 shrink-0" />
            <div className="text-info text-sm">
              Role assignments to teams are managed via Team Management. All
              members of a team inherit the team's roles.
            </div>
          </div>

          {/* Group list */}
          {groupsLoading ? (
            <div className="flex items-center justify-center py-8">
              <div className="text-secondary text-sm">Loading groups...</div>
            </div>
          ) : groupsError ? (
            <div className="border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4">
              <AlertCircle className="size-5 shrink-0" />
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
            <div className="text-tertiary py-8 text-center">
              <UsersRound className="mx-auto mb-2 size-8 opacity-50" />
              <div>No groups assigned this role</div>
              <div className="mt-1 text-sm">
                Assign this role to teams via Team Management
              </div>
            </div>
          ) : (
            <Card className="overflow-hidden">
              <CardContent className="p-0">
                <div className="border-border bg-secondary text-tertiary grid grid-cols-[1fr_1fr] gap-4 border-b px-4 py-2.5 text-xs font-medium tracking-wider uppercase">
                  <div>Group</div>
                  <div>Description</div>
                </div>
                <div className="divide-tertiary divide-y">
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
                          <div className="bg-secondary rounded p-1.5">
                            <UsersRound className="text-secondary size-4" />
                          </div>
                          <div className="min-w-0">
                            <div
                              className={
                                'text-primary truncate text-sm font-medium'
                              }
                            >
                              {group.name}
                            </div>
                            <div
                              className={
                                'text-tertiary truncate font-mono text-xs'
                              }
                            >
                              {group.slug}
                            </div>
                          </div>
                        </div>
                        <div className="text-tertiary truncate text-sm">
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
