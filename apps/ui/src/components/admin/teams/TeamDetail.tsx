import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Edit2, Users, UserPlus, X, Search, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { Gravatar } from '../../ui/gravatar'
import { DynamicDetailFields } from '../../ui/dynamic-fields'
import { getTeamMembers, addTeamMember, removeTeamMember, getTeamSchema } from '@/api/endpoints'
import type { Team } from '@/types'

const BASE_TEAM_FIELDS = new Set([
  'name', 'slug', 'description', 'icon', 'icon_url',
  'organization', 'organization_slug', 'created_at', 'last_modified_at',
])

function extractDynamicFields(team: Team): Record<string, unknown> {
  const result: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(team)) {
    if (!BASE_TEAM_FIELDS.has(key)) {
      result[key] = value
    }
  }
  return result
}

interface TeamDetailProps {
  team: Team
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function TeamDetail({ team, onEdit, onBack, isDarkMode }: TeamDetailProps) {
  const queryClient = useQueryClient()
  const [showAddMember, setShowAddMember] = useState(false)
  const [newMemberEmail, setNewMemberEmail] = useState('')

  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ['teamMembers', team.slug],
    queryFn: () => getTeamMembers(team.slug),
  })

  const { data: teamSchema } = useQuery({
    queryKey: ['teamSchema'],
    queryFn: getTeamSchema,
    staleTime: 5 * 60 * 1000,
  })

  const addMemberMutation = useMutation({
    mutationFn: (email: string) => addTeamMember(team.slug, email),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teamMembers', team.slug] })
      setNewMemberEmail('')
      setShowAddMember(false)
    },
    onError: (error: any) => {
      alert(`Failed to add member: ${error.response?.data?.detail || error.message}`)
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: (email: string) => removeTeamMember(team.slug, email),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['teamMembers', team.slug] })
    },
    onError: (error: any) => {
      alert(`Failed to remove member: ${error.response?.data?.detail || error.message}`)
    },
  })

  const handleAddMember = () => {
    if (!newMemberEmail.trim()) return
    addMemberMutation.mutate(newMemberEmail.trim())
  }

  const handleRemoveMember = (email: string) => {
    if (confirm('Remove this member from the team?')) {
      removeMemberMutation.mutate(email)
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onBack} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              {team.icon_url && (
                <img src={team.icon_url} alt="" className="w-8 h-8 rounded object-cover" />
              )}
              <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                {team.name}
              </h2>
            </div>
            {team.description && (
              <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {team.description}
              </p>
            )}
          </div>
        </div>
        <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Team
        </Button>
      </div>

      {/* Team Info */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Team Information
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Slug</div>
            <div className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              <code className={`px-2 py-1 rounded text-sm ${
                isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
              }`}>
                {team.slug}
              </code>
            </div>
          </div>
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Organization</div>
            <div className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              {team.organization.name}
            </div>
          </div>
          {teamSchema && (
            <DynamicDetailFields
              schema={teamSchema}
              data={extractDynamicFields(team)}
              isDarkMode={isDarkMode}
            />
          )}
        </div>
      </div>

      {/* Team Members */}
      <div className={`rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className={`p-6 border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className={`w-5 h-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
              <h3 className={`text-lg font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                Team Members
              </h3>
              <span className={`ml-2 px-2 py-1 rounded text-sm ${
                isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
              }`}>
                {members.length}
              </span>
            </div>
            <Button
              onClick={() => setShowAddMember(!showAddMember)}
              variant="outline"
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              <UserPlus className="w-4 h-4 mr-2" />
              Add Member
            </Button>
          </div>

          {/* Add Member Panel */}
          {showAddMember && (
            <div className={`mt-4 p-4 rounded-lg border ${
              isDarkMode ? 'bg-gray-750 border-gray-600' : 'bg-gray-50 border-gray-200'
            }`}>
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`} />
                  <Input
                    placeholder="Enter user email address..."
                    value={newMemberEmail}
                    onChange={(e) => setNewMemberEmail(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddMember()}
                    className={`pl-10 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
                  />
                </div>
                <Button
                  onClick={handleAddMember}
                  disabled={!newMemberEmail.trim() || addMemberMutation.isPending}
                  className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
                >
                  {addMemberMutation.isPending ? 'Adding...' : 'Add'}
                </Button>
              </div>
              {addMemberMutation.error && (
                <div className={`flex items-center gap-2 mt-2 text-xs ${
                  isDarkMode ? 'text-red-400' : 'text-red-600'
                }`}>
                  <AlertCircle className="w-3 h-3" />
                  {(addMemberMutation.error as any)?.response?.data?.detail || 'Failed to add member'}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Members List */}
        {membersLoading ? (
          <div className="p-8 text-center">
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              Loading members...
            </div>
          </div>
        ) : members.length === 0 ? (
          <div className={`text-center py-12 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            No members in this team yet. Click "Add Member" to get started.
          </div>
        ) : (
          <table className="w-full">
            <thead className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <tr>
                <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Member
                </th>
                <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Email
                </th>
                <th className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Status
                </th>
                <th className={`px-6 py-3 text-right text-xs font-medium uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
              {members.map((member) => (
                <tr key={member.email} className={isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'}>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <Gravatar
                        email={member.email}
                        size={32}
                        alt={member.display_name}
                        className="w-8 h-8 rounded-full"
                      />
                      <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                        {member.display_name}
                      </div>
                    </div>
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    {member.email}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${
                      member.is_active
                        ? isDarkMode ? 'bg-green-900/30 text-green-400' : 'bg-green-100 text-green-700'
                        : isDarkMode ? 'bg-gray-700 text-gray-400' : 'bg-gray-100 text-gray-600'
                    }`}>
                      {member.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleRemoveMember(member.email)}
                      disabled={removeMemberMutation.isPending}
                      className={`p-1.5 rounded ${
                        isDarkMode
                          ? 'text-red-400 hover:bg-red-900/20'
                          : 'text-red-600 hover:bg-red-50'
                      }`}
                      title="Remove from team"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
