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
          <ArrowLeft className="mr-2 size-4" />
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
                  className="size-8 rounded object-cover"
                  icon={team.icon}
                />
              )}
              <CardTitle>{team.name}</CardTitle>
            </div>
            {team.description && (
              <p className="text-secondary mt-1 text-sm">{team.description}</p>
            )}
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 size-4" />
            Edit Team
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-secondary text-sm">Slug</div>
              <div className="text-primary mt-1">
                <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                  {team.slug}
                </code>
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Organization</div>
              <div className="text-primary mt-1">{team.organization.name}</div>
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
              <Users className="text-secondary size-5" />
              <CardTitle>Team Members</CardTitle>
              <span className="bg-secondary text-primary ml-2 rounded px-2 py-1 text-sm">
                {members.length}
              </span>
            </div>
            <Button
              onClick={() => setShowAddMember(!showAddMember)}
              variant="outline"
            >
              <UserPlus className="mr-2 size-4" />
              Add Member
            </Button>
          </div>

          {/* Add Member Panel */}
          {showAddMember && (
            <div className="border-input bg-secondary mt-4 rounded-lg border p-4">
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2" />
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
                <div className="text-danger mt-2 flex items-center gap-2 text-xs">
                  <AlertCircle className="size-3" />
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
              <div className="text-secondary text-sm">Loading members...</div>
            </div>
          ) : membersError ? (
            <div className="text-danger p-8 text-center text-sm">
              {extractApiErrorDetail(
                membersError,
                'Failed to load team members',
              )}
            </div>
          ) : members.length === 0 ? (
            <div className="text-tertiary py-12 text-center">
              No members in this team yet. Click "Add Member" to get started.
            </div>
          ) : (
            <Table>
              <TableHeader className="border-tertiary bg-secondary border-b">
                <TableRow>
                  <TableHead className="text-tertiary px-6 py-3 text-left text-xs font-medium tracking-wider uppercase">
                    Member
                  </TableHead>
                  <TableHead className="text-tertiary px-6 py-3 text-left text-xs font-medium tracking-wider uppercase">
                    Email
                  </TableHead>
                  <TableHead className="text-tertiary px-6 py-3 text-left text-xs font-medium tracking-wider uppercase">
                    Status
                  </TableHead>
                  <TableHead className="text-tertiary px-6 py-3 text-right text-xs font-medium tracking-wider uppercase">
                    Actions
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody className="divide-tertiary divide-y">
                {members.map((member) => (
                  <TableRow className="hover:bg-secondary" key={member.email}>
                    <TableCell className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <Gravatar
                          alt={member.display_name}
                          className="size-8 rounded-full"
                          email={member.email}
                          size={32}
                        />
                        <div className="text-primary">
                          {member.display_name}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-secondary px-6 py-4 text-sm">
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
                              className="text-danger hover:bg-danger rounded p-1.5"
                              disabled={removeMemberMutation.isPending}
                              onClick={() => handleRemoveMember(member.email)}
                              title="Remove from team"
                              type="button"
                            >
                              <X className="size-4" />
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
