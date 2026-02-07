import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2, Users, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { TeamForm } from './teams/TeamForm'
import { TeamDetail } from './teams/TeamDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listTeams, deleteTeam, createTeam, updateTeam } from '@/api/endpoints'
import type { TeamCreate } from '@/types'

interface TeamManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

export function TeamManagement({ isDarkMode }: TeamManagementProps) {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedTeamSlug, setSelectedTeamSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data: teams = [], isLoading, error } = useQuery({
    queryKey: ['teams'],
    queryFn: listTeams,
  })

  const createMutation = useMutation({
    mutationFn: createTeam,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams'] })
      setViewMode('list')
      setSelectedTeamSlug(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, team }: { slug: string; team: TeamCreate }) =>
      updateTeam(slug, team),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams'] })
      setViewMode('list')
      setSelectedTeamSlug(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteTeam,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teams'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete team: ${error.response?.data?.detail || error.message}`)
    },
  })

  // Filter by selected org and search
  const filteredTeams = teams.filter((team) => {
    if (selectedOrganization && team.organization.slug !== selectedOrganization.slug) {
      return false
    }
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

  const selectedTeam = teams.find((t) => t.slug === selectedTeamSlug) || null

  const handleDelete = (slug: string) => {
    const team = teams.find((t) => t.slug === slug)
    if (team && confirm(`Delete team "${team.name}"? This action cannot be undone.`)) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (teamData: TeamCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(teamData)
    } else if (selectedTeamSlug) {
      updateMutation.mutate({ slug: selectedTeamSlug, team: teamData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedTeamSlug(null)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading teams...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load teams</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <TeamForm
        team={selectedTeam}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedTeam) {
    return (
      <TeamDetail
        team={selectedTeam}
        onEdit={() => {
          setSelectedTeamSlug(selectedTeam.slug)
          setViewMode('edit')
        }}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
      />
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="relative max-w-md">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <Input
              placeholder="Search teams..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={() => {
            setSelectedTeamSlug(null)
            setViewMode('create')
          }}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
        >
          <Plus className="w-4 h-4 mr-2" />
          New Team
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Total Teams
          </div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {filteredTeams.length}
          </div>
        </div>
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Total Projects
          </div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            &mdash;
          </div>
        </div>
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Total Members
          </div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            &mdash;
          </div>
        </div>
      </div>

      {/* Teams Table */}
      <div className={`rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <tr>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Team
                </th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Slug
                </th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Projects
                </th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Members
                </th>
                <th className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
              {filteredTeams.map((team) => (
                <tr
                  key={team.slug}
                  onClick={() => {
                    setSelectedTeamSlug(team.slug)
                    setViewMode('detail')
                  }}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        isDarkMode ? 'bg-blue-900/30' : 'bg-blue-50'
                      }`}>
                        {team.icon_url ? (
                          <img src={team.icon_url} alt="" className="w-5 h-5 rounded object-cover" />
                        ) : (
                          <Users className={`w-4 h-4 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`} />
                        )}
                      </div>
                      <div>
                        <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                          {team.name}
                        </div>
                        {team.description && (
                          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                            {team.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    <code className={`px-2 py-1 rounded ${
                      isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                    }`}>
                      {team.slug}
                    </code>
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    &mdash;
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    &mdash;
                  </td>
                  <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(team.slug)}
                        disabled={deleteMutation.isPending}
                        className={isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-red-900/20' : 'text-red-600 hover:text-red-700 hover:bg-red-50'}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredTeams.length === 0 && (
            <div className={`text-center py-12 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              {searchQuery
                ? 'No teams found matching your search.'
                : selectedOrganization
                  ? `No teams in ${selectedOrganization.name} yet.`
                  : 'No teams created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
