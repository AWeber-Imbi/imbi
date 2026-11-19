import { useState } from 'react'

import { ArrowRightLeft } from 'lucide-react'

import { handOffTicket } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/hooks/useAuth'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import type { Ticket, TicketHandOff } from '@/types'

import { useAgentList } from './agentQueries'
import { errorMessage, useTicketMutation } from './taskQueries'

/**
 * Hand a ticket to a person or an agent (ADR 0028). An agent ticket
 * goes to a person only. The owner, the assignee, and holders of
 * `ticket:manage` see it. Imbi refuses a ticket with an open session:
 * pause it first.
 */
export function HandOffControl({
  orgSlug,
  task,
}: {
  orgSlug: string
  task: Ticket
}) {
  const { user } = useAuth()
  const canManage = useHasPermission('ticket:manage', orgSlug)
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<'agent' | 'person'>('person')
  const [assignee, setAssignee] = useState('')
  const [agentSlug, setAgentSlug] = useState('')
  const [note, setNote] = useState('')
  const { users } = useUserDisplayNames()
  const isPerson = task.assignee_kind === 'person'
  const { data: agentList = [] } = useAgentList(
    open && isPerson ? orgSlug : undefined,
  )
  const handOff = useTicketMutation(
    orgSlug,
    task.short_id,
    (body: TicketHandOff) => handOffTicket(orgSlug, task.short_id, body),
  )
  const email = user?.email?.toLowerCase()
  const involved =
    !!email &&
    [task.owner, task.assignee].some((e) => e?.toLowerCase() === email)
  if (task.status === 'closed' || !(involved || canManage)) return null

  const toAgent = isPerson && kind === 'agent'
  const agents = agentList.filter((a) => a.enabled)
  return (
    <Popover
      onOpenChange={(next) => {
        setOpen(next)
        if (next) handOff.reset()
      }}
      open={open}
    >
      <PopoverTrigger asChild>
        <Button
          aria-label="Hand off ticket"
          size="sm"
          title="Hand off"
          variant="outline"
        >
          <ArrowRightLeft className="size-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-80 flex-col gap-3">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            handOff.mutate(
              {
                ...(toAgent
                  ? { agent_slug: agentSlug, assignee_kind: 'agent' }
                  : { assignee: assignee.trim(), assignee_kind: 'person' }),
                note: note.trim() || null,
              },
              {
                onSuccess: () => {
                  setOpen(false)
                  setAssignee('')
                  setNote('')
                },
              },
            )
          }}
        >
          {isPerson && (
            <SegmentedControl
              ariaLabel="Hand off to"
              onValueChange={(v) => setKind(v as 'agent' | 'person')}
              value={kind}
            >
              <SegmentedControlItem value="person">Person</SegmentedControlItem>
              <SegmentedControlItem value="agent">Agent</SegmentedControlItem>
            </SegmentedControl>
          )}
          {toAgent ? (
            <select
              aria-label="Agent"
              className="border-secondary bg-primary h-8 rounded-md border px-2 text-sm"
              onChange={(e) => setAgentSlug(e.target.value)}
              required
              value={agentSlug}
            >
              <option value="">Select an agent</option>
              {agents.map((a) => (
                <option key={a.slug} value={a.slug}>
                  {a.name}
                </option>
              ))}
            </select>
          ) : (
            <>
              <Input
                aria-label="Assignee email"
                className="h-8 text-sm"
                list="hand-off-assignees"
                onChange={(e) => setAssignee(e.target.value)}
                placeholder="person@example.com"
                required
                type="email"
                value={assignee}
              />
              <datalist id="hand-off-assignees">
                {users.map((u) => (
                  <option key={u.email} value={u.email}>
                    {u.display_name}
                  </option>
                ))}
              </datalist>
            </>
          )}
          <Textarea
            aria-label="Note"
            onChange={(e) => setNote(e.target.value)}
            placeholder="What should they do? (optional)"
            rows={2}
            value={note}
          />
          <p className="text-tertiary text-xs">
            Open questions to people close as withdrawn.
          </p>
          <Button disabled={handOff.isPending} size="sm" type="submit">
            Hand off
          </Button>
          {handOff.error && (
            <p className="text-danger text-xs" role="alert">
              {errorMessage(handOff.error)}
            </p>
          )}
        </form>
      </PopoverContent>
    </Popover>
  )
}
