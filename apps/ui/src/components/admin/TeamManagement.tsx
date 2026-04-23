import { useState, useMemo } from 'react'
import { Users } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { TeamForm } from './teams/TeamForm'
import { TeamDetail } from './teams/TeamDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { listTeams, deleteTeam, createTeam, updateTeam } from '@/api/endpoints'
import { buildDiffPatch } from '@/lib/json-patch'
import type { Team, TeamCreate, PatchOperation } from '@/types'

export function TeamManagement() {
  const { selectedOrganization } = useOrganization()
  const {
    viewMode,
    slug: selectedTeamSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    items: teams,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    Team,
    { orgSlug: string; team: TeamCreate },
    { orgSlug: string; slug: string; operations: PatchOperation[] },
    { orgSlug: string; slug: string }
  >({
    queryKey: ['teams', orgSlug],
    listFn: orgSlug ? (signal) => listTeams(orgSlug, signal) : null,
    createFn: ({ orgSlug, team }) => createTeam(orgSlug, team),
    updateFn: ({ orgSlug, slug, operations }) =>
      updateTeam(orgSlug, slug, operations),
    deleteFn: ({ orgSlug, slug }) => deleteTeam(orgSlug, slug),
    onMutationSuccess: goToList,
    deleteErrorLabel: 'team',
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
        ? [{ count: projects, label: 'project', href: '/projects' }]
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
        orgSlug: selectedTeam.organization.slug || formOrgSlug,
        slug: selectedTeamSlug,
        operations,
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
        team={selectedTeam}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedTeam) {
    return (
      <TeamDetail
        team={selectedTeam}
        onEdit={() => goToEdit(selectedTeam.slug)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <AdminSection
      searchPlaceholder="Search teams..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Team"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading teams..."
      error={error}
      errorTitle="Failed to load teams"
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
        columns={[
          {
            key: 'name',
            header: 'Team',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (team) => (
              <div className="flex items-center gap-3">
                <div className="flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-info">
                  {team.icon ? (
                    <EntityIcon
                      icon={team.icon}
                      className="size-5 rounded object-cover"
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
            key: 'slug',
            header: 'Slug',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (team) => (
              <code className="rounded bg-secondary px-2 py-1 text-primary">
                {team.slug}
              </code>
            ),
          },
          {
            key: 'projects',
            header: 'Projects',
            headerAlign: 'right',
            cellAlign: 'right',
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
            key: 'members',
            header: 'Members',
            headerAlign: 'right',
            cellAlign: 'right',
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
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (team) =>
              formatRelativeDate(team.updated_at ?? team.created_at),
          },
        ]}
        rows={filteredTeams}
        getRowKey={(team) => team.slug}
        getDeleteLabel={(team) => team.name}
        onRowClick={(team) => goToEdit(team.slug)}
        onDelete={handleDelete}
        canDelete={canDeleteTeam}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No teams found matching your search.'
            : selectedOrganization
              ? `No teams in ${selectedOrganization.name} yet.`
              : 'No teams created yet.'
        }
      />
    </AdminSection>
  )
}
