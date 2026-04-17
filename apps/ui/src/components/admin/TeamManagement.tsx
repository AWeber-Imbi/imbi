import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Users, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { TeamForm } from './teams/TeamForm'
import { TeamDetail } from './teams/TeamDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { listTeams, deleteTeam, createTeam, updateTeam } from '@/api/endpoints'
import type { Team, TeamCreate } from '@/types'

export function TeamManagement() {
  const queryClient = useQueryClient()
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
    data: teams = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: () => listTeams(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: ({ orgSlug, team }: { orgSlug: string; team: TeamCreate }) =>
      createTeam(orgSlug, team),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', orgSlug] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      orgSlug,
      slug,
      team,
    }: {
      orgSlug: string
      slug: string
      team: TeamCreate
    }) => updateTeam(orgSlug, slug, team),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', orgSlug] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ orgSlug, slug }: { orgSlug: string; slug: string }) =>
      deleteTeam(orgSlug, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams', orgSlug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete team: ${error.response?.data?.detail || error.message}`,
      )
    },
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
    } else if (selectedTeamSlug) {
      updateMutation.mutate({
        orgSlug: selectedTeam?.organization.slug || formOrgSlug,
        slug: selectedTeamSlug,
        team: teamData,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={'text-sm text-secondary'}>Loading teams...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${'border-danger bg-danger text-danger'}`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load teams</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  if (!orgSlug) {
    return (
      <div className={'py-12 text-center text-tertiary'}>
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="relative max-w-md">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${'text-tertiary'}`}
            />
            <Input
              placeholder="Search teams..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={'pl-10'}
            />
          </div>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Team
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="p-4">
            <CardDescription className={'text-secondary'}>
              Total Teams
            </CardDescription>
            <div className={'mt-1 text-2xl text-primary'}>
              {filteredTeams.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className={'text-secondary'}>
              Total Projects
            </CardDescription>
            <div className={'mt-1 text-2xl text-primary'}>
              {filteredTeams.reduce(
                (sum, t) => sum + (t.relationships?.projects?.count ?? 0),
                0,
              )}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className={'text-secondary'}>
              Total Members
            </CardDescription>
            <div className={'mt-1 text-2xl text-primary'}>
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
                <div
                  className={`flex size-8 flex-shrink-0 items-center justify-center rounded-lg ${'bg-info'}`}
                >
                  {team.icon ? (
                    <EntityIcon
                      icon={team.icon}
                      className="size-5 rounded object-cover"
                    />
                  ) : (
                    <Users className={'h-4 w-4 text-info'} />
                  )}
                </div>
                <div>
                  <div className={'text-primary'}>{team.name}</div>
                  {team.description && (
                    <div className={'text-sm text-tertiary'}>
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
              <code
                className={`rounded px-2 py-1 ${'bg-secondary text-primary'}`}
              >
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
    </div>
  )
}
