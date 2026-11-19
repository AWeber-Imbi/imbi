import { useState } from 'react'

import { Undo2 } from 'lucide-react'

import { reopenTicket } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { Textarea } from '@/components/ui/textarea'
import { useAuth } from '@/hooks/useAuth'
import { useHasPermission } from '@/hooks/useHasPermission'
import type { Ticket } from '@/types'

import { errorMessage, useTicketMutation } from './taskQueries'

/**
 * Reopen a closed ticket with a reason (ADR 0028). The ticket keeps its
 * assignee. The owner, the assignee, and holders of `ticket:manage` see
 * it.
 */
export function TicketReopen({
  orgSlug,
  task,
}: {
  orgSlug: string
  task: Ticket
}) {
  const { user } = useAuth()
  const canManage = useHasPermission('ticket:manage', orgSlug)
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const reopen = useTicketMutation(orgSlug, task.short_id, (text: string) =>
    reopenTicket(orgSlug, task.short_id, { reason: text }),
  )
  if (task.status !== 'closed') return null
  const email = user?.email?.toLowerCase()
  const involved =
    !!email &&
    (email === task.owner?.toLowerCase() ||
      email === task.assignee?.toLowerCase())
  if (!(involved || canManage)) return null
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <Button size="sm" variant="outline">
          <Undo2 className="mr-1 size-3.5" />
          Reopen
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-80 flex-col gap-2">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            reopen.mutate(reason.trim(), {
              onSuccess: () => {
                setOpen(false)
                setReason('')
              },
            })
          }}
        >
          <Textarea
            aria-label="Why reopen?"
            maxLength={64 * 1024}
            onChange={(e) => setReason(e.target.value)}
            placeholder="What is not done yet?"
            required
            rows={3}
            value={reason}
          />
          <Button
            className="self-end"
            disabled={reopen.isPending || !reason.trim()}
            size="sm"
            type="submit"
          >
            Reopen ticket
          </Button>
        </form>
        {reopen.error && (
          <p className="text-danger text-xs" role="alert">
            {errorMessage(reopen.error)}
          </p>
        )}
      </PopoverContent>
    </Popover>
  )
}
