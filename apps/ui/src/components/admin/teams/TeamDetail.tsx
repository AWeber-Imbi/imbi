import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import {
  ArrowLeft,
  Edit2,
  Users,
  UserPlus,
  X,
  Search,
  AlertCircle,
} from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { Gravatar } from '../../ui/gravatar'
import { DynamicDetailFields } from '../../ui/dynamic-fields'
import {
  getTeamMembers,
  addTeamMember,
  removeTeamMember,
  getTeamSchema,
} from '@/api/endpoints'
import { TEAM_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields } from '@/lib/utils'
import type { Team } from '@/types'

interface TeamDetailProps {
  team: Team
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function TeamDetail({
  team,
  onEdit,
  onBack,
  isDarkMode,
}: TeamDetailProps) {
  const queryClient = useQueryClient()
  const [showAddMember, setShowAddMember] = useState(false)
  const [newMemberEmail, setNewMemberEmail] = useState('')

  const { data: members = [], isLoading: membersLoading } = useQuery({
    queryKey: ['teamMembers', team.organization.slug, team.slug],
    queryFn: () => getTeamMembers(team.organization.slug, team.slug),
  })

  const { data: teamSchema } = useQuery({
    queryKey: ['teamSchema'],
    queryFn: getTeamSchema,
    staleTime: 5 * 60 * 1000,
  })

  const addMemberMutation = useMutation({
    mutationFn: (email: string) =>
      addTeamMember(team.organization.slug, team.slug, email),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['teamMembers', team.organization.slug, team.slug],
      })
      setNewMemberEmail('')
      setShowAddMember(false)
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to add member: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: (email: string) =>
      removeTeamMember(team.organization.slug, team.slug, email),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['teamMembers', team.organization.slug, team.slug],
      })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to remove member: ${error.response?.data?.detail || error.message}`,
      )
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
          <Button
            variant="outline"
            onClick={onBack}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              {team.icon && (
                <img
                  src={team.icon}
                  alt=""
                  className="h-8 w-8 rounded object-cover"
                />
              )}
              <h2
                className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {team.name}
              </h2>
            </div>
            {team.description && (
              <p
                className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {team.description}
              </p>
            )}
          </div>
        </div>
        <Button
          onClick={onEdit}
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Edit2 className="mr-2 h-4 w-4" />
          Edit Team
        </Button>
      </div>

      {/* Team Info */}
      <div
        className={`rounded-lg border p-6 ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <h3
          className={`mb-4 text-lg font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
        >
          Team Information
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Slug
            </div>
            <div
              className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
            >
              <code
                className={`rounded px-2 py-1 text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 text-gray-300'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                {team.slug}
              </code>
            </div>
          </div>
          <div>
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Organization
            </div>
            <div
              className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
            >
              {team.organization.name}
            </div>
          </div>
          {teamSchema && (
            <DynamicDetailFields
              schema={teamSchema}
              data={extractDynamicFields(team, TEAM_BASE_FIELDS_SET)}
              isDarkMode={isDarkMode}
            />
          )}
        </div>
      </div>

      {/* Team Members */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div
          className={`border-b p-6 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users
                className={`h-5 w-5 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              />
              <h3
                className={`text-lg font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                Team Members
              </h3>
              <span
                className={`ml-2 rounded px-2 py-1 text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 text-gray-300'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                {members.length}
              </span>
            </div>
            <Button
              onClick={() => setShowAddMember(!showAddMember)}
              variant="outline"
              className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
            >
              <UserPlus className="mr-2 h-4 w-4" />
              Add Member
            </Button>
          </div>

          {/* Add Member Panel */}
          {showAddMember && (
            <div
              className={`mt-4 rounded-lg border p-4 ${
                isDarkMode
                  ? 'bg-gray-750 border-gray-600'
                  : 'border-gray-200 bg-gray-50'
              }`}
            >
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search
                    className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                      isDarkMode ? 'text-gray-400' : 'text-gray-500'
                    }`}
                  />
                  <Input
                    placeholder="Enter user email address..."
                    value={newMemberEmail}
                    onChange={(e) => setNewMemberEmail(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddMember()}
                    className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
                  />
                </div>
                <Button
                  onClick={handleAddMember}
                  disabled={
                    !newMemberEmail.trim() || addMemberMutation.isPending
                  }
                  className="bg-[#2A4DD0] text-white hover:bg-blue-700"
                >
                  {addMemberMutation.isPending ? 'Adding...' : 'Add'}
                </Button>
              </div>
              {addMemberMutation.error && (
                <div
                  className={`mt-2 flex items-center gap-2 text-xs ${
                    isDarkMode ? 'text-red-400' : 'text-red-600'
                  }`}
                >
                  <AlertCircle className="h-3 w-3" />
                  {(addMemberMutation.error as AxiosError<{ detail?: string }>)
                    ?.response?.data?.detail || 'Failed to add member'}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Members List */}
        {membersLoading ? (
          <div className="p-8 text-center">
            <div
              className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Loading members...
            </div>
          </div>
        ) : members.length === 0 ? (
          <div
            className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            No members in this team yet. Click "Add Member" to get started.
          </div>
        ) : (
          <table className="w-full">
            <thead
              className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
            >
              <tr>
                <th
                  className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Member
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Email
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Status
                </th>
                <th
                  className={`px-6 py-3 text-right text-xs font-medium uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody
              className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}
            >
              {members.map((member) => (
                <tr
                  key={member.email}
                  className={
                    isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'
                  }
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <Gravatar
                        email={member.email}
                        size={32}
                        alt={member.display_name}
                        className="h-8 w-8 rounded-full"
                      />
                      <div
                        className={isDarkMode ? 'text-white' : 'text-gray-900'}
                      >
                        {member.display_name}
                      </div>
                    </div>
                  </td>
                  <td
                    className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    {member.email}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className={`inline-flex items-center rounded px-2 py-1 text-xs font-medium ${
                        member.is_active
                          ? isDarkMode
                            ? 'bg-green-900/30 text-green-400'
                            : 'bg-green-100 text-green-700'
                          : isDarkMode
                            ? 'bg-gray-700 text-gray-400'
                            : 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {member.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => handleRemoveMember(member.email)}
                      disabled={removeMemberMutation.isPending}
                      className={`rounded p-1.5 ${
                        isDarkMode
                          ? 'text-red-400 hover:bg-red-900/20'
                          : 'text-red-600 hover:bg-red-50'
                      }`}
                      title="Remove from team"
                    >
                      <X className="h-4 w-4" />
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
