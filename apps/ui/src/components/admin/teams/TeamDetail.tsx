import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { extractApiErrorDetail } from '@/lib/apiError'
import {
  ArrowLeft,
  Edit2,
  Users,
  UserPlus,
  X,
  Search,
  AlertCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Gravatar } from '@/components/ui/gravatar'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import {
  getTeamMembers,
  addTeamMember,
  removeTeamMember,
  getTeamSchema,
} from '@/api/endpoints'
import { TEAM_BASE_FIELDS_SET } from '@/lib/constants'
import { EntityIcon } from '@/components/ui/entity-icon'
import { extractDynamicFields } from '@/lib/utils'
import type { Team } from '@/types'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

interface TeamDetailProps {
  team: Team
  onEdit: () => void
  onBack: () => void
}

export function TeamDetail({ team, onEdit, onBack }: TeamDetailProps) {
  const queryClient = useQueryClient()
  const [showAddMember, setShowAddMember] = useState(false)
  const [newMemberEmail, setNewMemberEmail] = useState('')

  const {
    data: members = [],
    isLoading: membersLoading,
    error: membersError,
  } = useQuery({
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
    onError: (error: unknown) => {
      toast.error(`Failed to add member: ${extractApiErrorDetail(error)}`)
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
    onError: (error: unknown) => {
      toast.error(`Failed to remove member: ${extractApiErrorDetail(error)}`)
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
      {/* Back button */}
      <div>
        <Button variant="outline" onClick={onBack}>
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Team info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div>
            <div className="flex items-center gap-3">
              {team.icon && (
                <EntityIcon
                  icon={team.icon}
                  className="h-8 w-8 rounded object-cover"
                />
              )}
              <CardTitle>{team.name}</CardTitle>
            </div>
            {team.description && (
              <p className="mt-1 text-sm text-secondary">{team.description}</p>
            )}
          </div>
          <Button
            onClick={onEdit}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Team
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-sm text-secondary">Slug</div>
              <div className="mt-1 text-primary">
                <code
                  className={`rounded bg-secondary px-2 py-1 text-sm text-primary`}
                >
                  {team.slug}
                </code>
              </div>
            </div>
            <div>
              <div className="text-sm text-secondary">Organization</div>
              <div className="mt-1 text-primary">{team.organization.name}</div>
            </div>
            {teamSchema && (
              <DynamicDetailFields
                schema={teamSchema}
                data={extractDynamicFields(team, TEAM_BASE_FIELDS_SET)}
              />
            )}
          </div>
        </CardContent>
      </Card>

      {/* Team Members */}
      <Card>
        <CardHeader className="space-y-0 border-b px-6 py-5">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users className="h-5 w-5 text-secondary" />
              <CardTitle>Team Members</CardTitle>
              <span
                className={`ml-2 rounded bg-secondary px-2 py-1 text-sm text-primary`}
              >
                {members.length}
              </span>
            </div>
            <Button
              onClick={() => setShowAddMember(!showAddMember)}
              variant="outline"
            >
              <UserPlus className="mr-2 h-4 w-4" />
              Add Member
            </Button>
          </div>

          {/* Add Member Panel */}
          {showAddMember && (
            <div
              className={`mt-4 rounded-lg border border-input bg-secondary p-4`}
            >
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search
                    className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary`}
                  />
                  <Input
                    placeholder="Enter user email address..."
                    value={newMemberEmail}
                    onChange={(e) => setNewMemberEmail(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddMember()}
                    className="pl-10"
                  />
                </div>
                <Button
                  onClick={handleAddMember}
                  disabled={
                    !newMemberEmail.trim() || addMemberMutation.isPending
                  }
                  className="bg-action text-action-foreground hover:bg-action-hover"
                >
                  {addMemberMutation.isPending ? 'Adding...' : 'Add'}
                </Button>
              </div>
              {!!addMemberMutation.error && (
                <div
                  className={`mt-2 flex items-center gap-2 text-xs text-danger`}
                >
                  <AlertCircle className="h-3 w-3" />
                  {extractApiErrorDetail(
                    addMemberMutation.error,
                    'Failed to add member',
                  )}
                </div>
              )}
            </div>
          )}
        </CardHeader>

        {/* Members List */}
        <CardContent className="p-0">
          {membersLoading ? (
            <div className="p-8 text-center">
              <div className="text-sm text-secondary">Loading members...</div>
            </div>
          ) : membersError ? (
            <div className="p-8 text-center text-sm text-danger">
              {extractApiErrorDetail(
                membersError,
                'Failed to load team members',
              )}
            </div>
          ) : members.length === 0 ? (
            <div className="py-12 text-center text-tertiary">
              No members in this team yet. Click "Add Member" to get started.
            </div>
          ) : (
            <table className="w-full">
              <thead className="border-b border-tertiary bg-secondary">
                <tr>
                  <th
                    className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary`}
                  >
                    Member
                  </th>
                  <th
                    className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary`}
                  >
                    Email
                  </th>
                  <th
                    className={`px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary`}
                  >
                    Status
                  </th>
                  <th
                    className={`px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-tertiary`}
                  >
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-tertiary">
                {members.map((member) => (
                  <tr key={member.email} className="hover:bg-secondary">
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <Gravatar
                          email={member.email}
                          size={32}
                          alt={member.display_name}
                          className="h-8 w-8 rounded-full"
                        />
                        <div className="text-primary">
                          {member.display_name}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4 text-sm text-secondary">
                      {member.email}
                    </td>
                    <td className="px-6 py-4">
                      <Badge variant={member.is_active ? 'success' : 'neutral'}>
                        {member.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              type="button"
                              onClick={() => handleRemoveMember(member.email)}
                              disabled={removeMemberMutation.isPending}
                              aria-label={`Remove ${member.display_name} from team`}
                              title="Remove from team"
                              className={`rounded p-1.5 text-danger hover:bg-danger`}
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Remove from team</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
