import { useState } from 'react'

import { Ban, CircleCheck, Play } from 'lucide-react'

import { setTicketStatus } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/hooks/useAuth'
import { useHasPermission } from '@/hooks/useHasPermission'
import type { Ticket, TicketStatusSet } from '@/types'

import { errorMessage, useTicketMutation } from './taskQueries'

type Outcome = NonNullable<TicketStatusSet['outcome']>

const OUTCOMES: { label: string; value: Outcome }[] = [
  { label: 'Done', value: 'done_acted' },
  { label: 'Nothing to do', value: 'done_nothing_to_act_on' },
  { label: 'Superseded', value: 'superseded' },
  { label: 'Cancelled', value: 'cancelled_by_human' },
]

/**
 * The status controls of a person ticket (ADR 0028): start, block with
 * a reason, unblock, and close with an outcome. The assignee and holders
 * of `ticket:manage` see them. A held ticket opens by its gates only.
 */
export function PersonStatusControls({
  orgSlug,
  task,
}: {
  orgSlug: string
  task: Ticket
}) {
  const { user } = useAuth()
  const canManage = useHasPermission('ticket:manage', orgSlug)
  const [form, setForm] = useState<'blocked' | 'closed' | null>(null)
  const [reason, setReason] = useState('')
  const [outcome, setOutcome] = useState<Outcome>('done_acted')
  const move = useTicketMutation(
    orgSlug,
    task.short_id,
    (body: TicketStatusSet) => setTicketStatus(orgSlug, task.short_id, body),
  )
  const isAssignee =
    !!user?.email && user.email.toLowerCase() === task.assignee?.toLowerCase()
  if (task.status === 'closed' || !(isAssignee || canManage)) return null

  const submit = (body: TicketStatusSet) =>
    move.mutate(body, {
      onSuccess: () => {
        setForm(null)
        setReason('')
      },
    })
  const note = reason.trim() || null
  // Only an open or started ticket can block.
  const forms: ('blocked' | 'closed')[] =
    task.status === 'open' || task.status === 'in_progress'
      ? ['blocked', 'closed']
      : ['closed']
  return (
    <div className="flex shrink-0 items-center gap-1">
      {(task.status === 'open' || task.status === 'blocked') && (
        <Button
          disabled={move.isPending}
          onClick={() => submit({ status: 'in_progress' })}
          size="sm"
          variant="outline"
        >
          <Play className="mr-1 size-3.5" />
          {task.status === 'open' ? 'Start' : 'Unblock'}
        </Button>
      )}
      {forms.map((to) => (
        <Popover
          key={to}
          onOpenChange={(open) => setForm(open ? to : null)}
          open={form === to}
        >
          <PopoverTrigger asChild>
            <Button size="sm" variant="outline">
              {to === 'blocked' ? (
                <Ban className="mr-1 size-3.5" />
              ) : (
                <CircleCheck className="mr-1 size-3.5" />
              )}
              {to === 'blocked' ? 'Block' : 'Close'}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="flex flex-col gap-3">
            <form
              className="flex flex-col gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                submit(
                  to === 'blocked'
                    ? { reason: note, status: 'blocked' }
                    : { outcome, reason: note, status: 'closed' },
                )
              }}
            >
              {to === 'closed' && (
                <select
                  aria-label="Outcome"
                  className="border-secondary bg-primary h-8 rounded-md border px-2 text-sm"
                  onChange={(e) => setOutcome(e.target.value as Outcome)}
                  value={outcome}
                >
                  {OUTCOMES.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
              )}
              <Textarea
                aria-label={to === 'blocked' ? 'Why is it blocked?' : 'Note'}
                onChange={(e) => setReason(e.target.value)}
                placeholder={
                  to === 'blocked' ? 'Waiting on…' : 'Note (optional)'
                }
                required={to === 'blocked'}
                rows={2}
                value={reason}
              />
              <Button disabled={move.isPending} size="sm" type="submit">
                {to === 'blocked' ? 'Block' : 'Close ticket'}
              </Button>
            </form>
          </PopoverContent>
        </Popover>
      ))}
      {move.error && (
        <span className="text-danger text-xs" role="alert">
          {errorMessage(move.error)}
        </span>
      )}
    </div>
  )
}
