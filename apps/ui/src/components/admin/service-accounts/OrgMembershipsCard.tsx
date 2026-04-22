import { useEffect, useState } from 'react'
import type { UseMutationResult } from '@tanstack/react-query'
import { Plus, Trash2, Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { ServiceAccount, OrgMembership, Role } from '@/types'

interface OrgMembershipsCardProps {
  account: ServiceAccount
  availableRoles: Role[]
  rolesLoading: boolean
  rolesError: boolean
  addOrgMutation: UseMutationResult<
    unknown,
    unknown,
    { organization_slug: string; role_slug: string }
  >
  updateOrgRoleMutation: UseMutationResult<
    unknown,
    unknown,
    { orgSlug: string; roleSlug: string }
  >
  removeOrgMutation: UseMutationResult<unknown, unknown, string>
  onConfirmRemove: (orgSlug: string, orgName: string) => void
}

export function OrgMembershipsCard({
  account,
  availableRoles,
  rolesLoading,
  rolesError,
  addOrgMutation,
  updateOrgRoleMutation,
  removeOrgMutation,
  onConfirmRemove,
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
                {rolesLoading ? (
                  <p className="text-sm text-secondary">Loading roles...</p>
                ) : rolesError ? (
                  <p className="text-sm text-danger">Failed to load roles</p>
                ) : (
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
                )}
              </div>
            </div>
            <div className="mt-3 flex items-center gap-2">
              <Button
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
        {(account.organizations ?? []).length > 0 ? (
          <div className="space-y-2">
            {(account.organizations ?? []).map((membership: OrgMembership) => (
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
                  {rolesLoading ? (
                    <span className="text-xs text-secondary">
                      Loading roles...
                    </span>
                  ) : rolesError ? (
                    <span className="text-xs text-danger">
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
                      className="rounded border border-input bg-background px-2 py-1 text-xs text-foreground"
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
                          onClick={() =>
                            onConfirmRemove(
                              membership.organization_slug,
                              membership.organization_name,
                            )
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
              This service account has no permissions until added to an
              organization
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
