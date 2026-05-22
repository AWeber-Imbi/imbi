import { useEffect, useState } from 'react'

import type { UseMutationResult } from '@tanstack/react-query'
import { Building2, Plus, Trash2 } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { OrgMembership, Role, ServiceAccount } from '@/types'

interface OrgMembershipsCardProps {
  account: ServiceAccount
  addOrgMutation: UseMutationResult<
    unknown,
    unknown,
    { organization_slug: string; role_slug: string }
  >
  availableRoles: Role[]
  onConfirmRemove: (orgSlug: string, orgName: string) => void
  removeOrgMutation: UseMutationResult<unknown, unknown, string>
  rolesError: boolean
  rolesLoading: boolean
  updateOrgRoleMutation: UseMutationResult<
    unknown,
    unknown,
    { orgSlug: string; roleSlug: string }
  >
}

export function OrgMembershipsCard({
  account,
  addOrgMutation,
  availableRoles,
  onConfirmRemove,
  removeOrgMutation,
  rolesError,
  rolesLoading,
  updateOrgRoleMutation,
}: OrgMembershipsCardProps) {
  const { organizations: allOrgs } = useOrganization()
  const [showAddOrg, setShowAddOrg] = useState(false)
  const [newOrgSlug, setNewOrgSlug] = useState('')
  const [newRoleSlug, setNewRoleSlug] = useState('')

  useEffect(() => {
    setShowAddOrg(false)
    setNewOrgSlug('')
    setNewRoleSlug('')
  }, [account.slug])

  const memberOrgSlugs = new Set(
    (account.organizations ?? []).map((o) => o.organization_slug),
  )
  const availableOrgs = allOrgs.filter((o) => !memberOrgSlugs.has(o.slug))

  return (
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
                <Select onValueChange={setNewOrgSlug} value={newOrgSlug}>
                  <SelectTrigger aria-label="Organization">
                    <SelectValue placeholder="Select..." />
                  </SelectTrigger>
                  <SelectContent>
                    {availableOrgs.map((org) => (
                      <SelectItem key={org.slug} value={org.slug}>
                        {org.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-secondary mb-1.5 block text-sm">
                  Role
                </label>
                {rolesLoading ? (
                  <p className="text-secondary text-sm">Loading roles...</p>
                ) : rolesError ? (
                  <p className="text-danger text-sm">Failed to load roles</p>
                ) : (
                  <Select onValueChange={setNewRoleSlug} value={newRoleSlug}>
                    <SelectTrigger aria-label="Role">
                      <SelectValue placeholder="Select..." />
                    </SelectTrigger>
                    <SelectContent>
                      {availableRoles.map((role) => (
                        <SelectItem key={role.slug} value={role.slug}>
                          {role.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Button
                className="bg-action text-action-foreground hover:bg-action-hover"
                disabled={
                  !newOrgSlug || !newRoleSlug || addOrgMutation.isPending
                }
                onClick={() =>
                  addOrgMutation.mutate(
                    {
                      organization_slug: newOrgSlug,
                      role_slug: newRoleSlug,
                    },
                    {
                      onSuccess: () => {
                        setShowAddOrg(false)
                        setNewOrgSlug('')
                        setNewRoleSlug('')
                      },
                    },
                  )
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
        {(account.organizations ?? []).length > 0 ? (
          <div className="space-y-2">
            {(account.organizations ?? []).map((membership: OrgMembership) => (
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
                  {rolesLoading ? (
                    <span className="text-secondary text-xs">
                      Loading roles...
                    </span>
                  ) : rolesError ? (
                    <span className="text-danger text-xs">
                      Roles unavailable
                    </span>
                  ) : (
                    <Select
                      disabled={updateOrgRoleMutation.isPending}
                      onValueChange={(roleSlug) =>
                        updateOrgRoleMutation.mutate({
                          orgSlug: membership.organization_slug,
                          roleSlug,
                        })
                      }
                      value={membership.role}
                    >
                      <SelectTrigger
                        aria-label={`Role for ${membership.organization_name}`}
                        className="h-7 w-auto text-xs"
                      >
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {availableRoles.map((role) => (
                          <SelectItem key={role.slug} value={role.slug}>
                            {role.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button
                          aria-label={`Remove from ${membership.organization_name}`}
                          className="text-danger hover:bg-secondary size-7"
                          disabled={removeOrgMutation.isPending}
                          onClick={() =>
                            onConfirmRemove(
                              membership.organization_slug,
                              membership.organization_name,
                            )
                          }
                          size="icon"
                          type="button"
                          variant="ghost"
                        >
                          <Trash2 className="size-4" />
                        </Button>
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
              This service account has no permissions until added to an
              organization
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
