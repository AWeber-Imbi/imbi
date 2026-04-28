import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowLeft,
  Edit2,
  Search,
  UserPlus,
  Users,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  addTeamMember,
  getTeamMembers,
  getTeamSchema,
  removeTeamMember,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Gravatar } from '@/components/ui/gravatar'
import { Input } from '@/components/ui/input'
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
import { TEAM_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields } from '@/lib/utils'
import type { Team } from '@/types'

interface TeamDetailProps {
  onBack: () => void
  onEdit: () => void
  team: Team
}

export function TeamDetail({ onBack, onEdit, team }: TeamDetailProps) {
  const queryClient = useQueryClient()
  const [showAddMember, setShowAddMember] = useState(false)
  const [newMemberEmail, setNewMemberEmail] = useState('')
  const [confirm, setConfirm] = useState<null | {
    action: 'remove'
    email: string
  }>(null)

  const {
    data: members = [],
    error: membersError,
    isLoading: membersLoading,
  } = useQuery({
    queryFn: ({ signal }) =>
      getTeamMembers(team.organization.slug, team.slug, signal),
    queryKey: ['teamMembers', team.organization.slug, team.slug],
  })

  const { data: teamSchema } = useQuery({
    queryFn: ({ signal }) => getTeamSchema(signal),
    queryKey: ['teamSchema'],
    staleTime: 5 * 60 * 1000,
  })

  const addMemberMutation = useMutation({
    mutationFn: (email: string) =>
      addTeamMember(team.organization.slug, team.slug, email),
    onError: (error: unknown) => {
      toast.error(`Failed to add member: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['teamMembers', team.organization.slug, team.slug],
      })
      setNewMemberEmail('')
      setShowAddMember(false)
    },
  })

  const removeMemberMutation = useMutation({
    mutationFn: (email: string) =>
      removeTeamMember(team.organization.slug, team.slug, email),
    onError: (error: unknown) => {
      toast.error(`Failed to remove member: ${extractApiErrorDetail(error)}`)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['teamMembers', team.organization.slug, team.slug],
      })
    },
  })

  const handleAddMember = () => {
    if (!newMemberEmail.trim()) return
    addMemberMutation.mutate(newMemberEmail.trim())
  }

  const handleRemoveMember = (email: string) => {
    setConfirm({ action: 'remove', email })
  }

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
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
                  className="h-8 w-8 rounded object-cover"
                  icon={team.icon}
                />
              )}
              <CardTitle>{team.name}</CardTitle>
            </div>
            {team.description && (
              <p className="mt-1 text-sm text-secondary">{team.description}</p>
            )}
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
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
                <code className="rounded bg-secondary px-2 py-1 text-sm text-primary">
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
                data={extractDynamicFields(team, TEAM_BASE_FIELDS_SET)}
                schema={teamSchema}
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
              <span className="ml-2 rounded bg-secondary px-2 py-1 text-sm text-primary">
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
            <div className="mt-4 rounded-lg border border-input bg-secondary p-4">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
                  <Input
                    className="pl-10"
                    onChange={(e) => setNewMemberEmail(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddMember()}
                    placeholder="Enter user email address..."
                    value={newMemberEmail}
                  />
                </div>
                <Button
                  className="bg-action text-action-foreground hover:bg-action-hover"
                  disabled={
                    !newMemberEmail.trim() || addMemberMutation.isPending
                  }
                  onClick={handleAddMember}
                >
                  {addMemberMutation.isPending ? 'Adding...' : 'Add'}
                </Button>
              </div>
              {!!addMemberMutation.error && (
                <div className="mt-2 flex items-center gap-2 text-xs text-danger">
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
            <Table>
              <TableHeader className="border-b border-tertiary bg-secondary">
                <TableRow>
                  <TableHead className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary">
                    Member
                  </TableHead>
                  <TableHead className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary">
                    Email
                  </TableHead>
                  <TableHead className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-tertiary">
                    Status
                  </TableHead>
                  <TableHead className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-tertiary">
                    Actions
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="divide-y divide-tertiary">
                {members.map((member) => (
                  <TableRow className="hover:bg-secondary" key={member.email}>
                    <TableCell className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <Gravatar
                          alt={member.display_name}
                          className="h-8 w-8 rounded-full"
                          email={member.email}
                          size={32}
                        />
                        <div className="text-primary">
                          {member.display_name}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="px-6 py-4 text-sm text-secondary">
                      {member.email}
                    </TableCell>
                    <TableCell className="px-6 py-4">
                      <Badge variant={member.is_active ? 'success' : 'neutral'}>
                        {member.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </TableCell>
                    <TableCell className="px-6 py-4 text-right">
                      <TooltipProvider delayDuration={200}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <button
                              aria-label={`Remove ${member.display_name} from team`}
                              className="rounded p-1.5 text-danger hover:bg-danger"
                              disabled={removeMemberMutation.isPending}
                              onClick={() => handleRemoveMember(member.email)}
                              title="Remove from team"
                              type="button"
                            >
                              <X className="h-4 w-4" />
                            </button>
                          </TooltipTrigger>
                          <TooltipContent>
                            <p>Remove from team</p>
                          </TooltipContent>
                        </Tooltip>
                      </TooltipProvider>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <ConfirmDialog
        confirmLabel="Remove"
        description="Remove this member from the team?"
        onCancel={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm?.action === 'remove') {
            removeMemberMutation.mutate(confirm.email)
          }
          setConfirm(null)
        }}
        open={confirm?.action === 'remove'}
        title="Remove team member"
      />
    </div>
  )
}
