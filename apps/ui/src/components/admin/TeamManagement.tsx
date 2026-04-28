import { useMemo, useState } from 'react'

import { Users } from 'lucide-react'

import { createTeam, deleteTeam, listTeams, updateTeam } from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type { PatchOperation, Team, TeamCreate } from '@/types'

import { AdminSection } from './AdminSection'
import { TeamDetail } from './teams/TeamDetail'
import { TeamForm } from './teams/TeamForm'

export function TeamManagement() {
  const { selectedOrganization } = useOrganization()
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedTeamSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: teams,
    updateMutation,
  } = useAdminCrud<
    Team,
    { orgSlug: string; team: TeamCreate },
    { operations: PatchOperation[]; orgSlug: string; slug: string },
    { orgSlug: string; slug: string }
  >({
    createFn: ({ orgSlug, team }) => createTeam(orgSlug, team),
    deleteErrorLabel: 'team',
    deleteFn: ({ orgSlug, slug }) => deleteTeam(orgSlug, slug),
    listFn: orgSlug ? (signal) => listTeams(orgSlug, signal) : null,
    onMutationSuccess: goToList,
    queryKey: ['teams', orgSlug],
    updateFn: ({ operations, orgSlug, slug }) =>
      updateTeam(orgSlug, slug, operations),
  })

  const filteredTeams = teams.filter((team) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        team.name.toLowerCase().includes(query) ||
        team.slug.toLowerCase().includes(query) ||
        (team.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedTeam = useMemo(
    () => teams.find((t) => t.slug === selectedTeamSlug) || null,
    [teams, selectedTeamSlug],
  )

  const handleDelete = (team: Team) => {
    deleteMutation.mutate({ orgSlug: team.organization.slug, slug: team.slug })
  }

  const canDeleteTeam = (team: Team): CanDeleteResult => {
    const projects = team.relationships?.projects?.count ?? 0
    const members = team.relationships?.members?.count ?? 0
    if (projects === 0 && members === 0) return { allowed: true }
    const blockedBy = [
      ...(projects > 0
        ? [{ count: projects, href: '/projects', label: 'project' }]
        : []),
      ...(members > 0 ? [{ count: members, label: 'member' }] : []),
    ]
    return { allowed: false, blockedBy }
  }

  const handleSave = (formOrgSlug: string, teamData: TeamCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, team: teamData })
    } else if (selectedTeamSlug && selectedTeam) {
      const operations = buildDiffPatch(
        selectedTeam as unknown as Record<string, unknown>,
        teamData as unknown as Record<string, unknown>,
        { fields: Object.keys(teamData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({
        operations,
        orgSlug: selectedTeam.organization.slug || formOrgSlug,
        slug: selectedTeamSlug,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (!orgSlug && !isLoading && !error) {
    return (
      <div className="py-12 text-center text-tertiary">
        Select an organization to manage teams.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <TeamForm
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
        team={selectedTeam}
      />
    )
  }

  if (viewMode === 'detail' && selectedTeam) {
    return (
      <TeamDetail
        onBack={handleCancel}
        onEdit={() => goToEdit(selectedTeam.slug)}
        team={selectedTeam}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Team"
      error={error}
      errorTitle="Failed to load teams"
      isLoading={isLoading}
      loadingLabel="Loading teams..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search teams..."
    >
      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Teams
            </CardDescription>
            <div className="mt-1 text-2xl text-primary">
              {filteredTeams.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Projects
            </CardDescription>
            <div className="mt-1 text-2xl text-primary">
              {filteredTeams.reduce(
                (sum, t) => sum + (t.relationships?.projects?.count ?? 0),
                0,
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Members
            </CardDescription>
            <div className="mt-1 text-2xl text-primary">
              {filteredTeams.reduce(
                (sum, t) => sum + (t.relationships?.members?.count ?? 0),
                0,
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <AdminTable
        canDelete={canDeleteTeam}
        columns={[
          {
            cellAlign: 'left',
            header: 'Team',
            headerAlign: 'left',
            key: 'name',
            render: (team) => (
              <div className="flex items-center gap-3">
                <div className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info">
                  {team.icon ? (
                    <EntityIcon
                      className="size-5 rounded object-cover"
                      icon={team.icon}
                    />
                  ) : (
                    <Users className="h-4 w-4 text-info" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{team.name}</div>
                  {team.description && (
                    <div className="text-sm text-tertiary">
                      {team.description}
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Slug',
            headerAlign: 'center',
            key: 'slug',
            render: (team) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {team.slug}
              </code>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Projects',
            headerAlign: 'right',
            key: 'projects',
            render: (team) => (
              <span
                className={
                  (team.relationships?.projects?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {team.relationships?.projects?.count ?? 0}
              </span>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Members',
            headerAlign: 'right',
            key: 'members',
            render: (team) => (
              <span
                className={
                  (team.relationships?.members?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {team.relationships?.members?.count ?? 0}
              </span>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (team) =>
              formatRelativeDate(team.updated_at ?? team.created_at),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No teams found matching your search.'
            : selectedOrganization
              ? `No teams in ${selectedOrganization.name} yet.`
              : 'No teams created yet.'
        }
        getDeleteLabel={(team) => team.name}
        getRowKey={(team) => team.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(team) => goToEdit(team.slug)}
        rows={filteredTeams}
      />
    </AdminSection>
  )
}
