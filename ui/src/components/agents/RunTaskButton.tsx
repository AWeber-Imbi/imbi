import { useState } from 'react'

import { Play } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { useHasPermission } from '@/hooks/useHasPermission'
import type { Agent } from '@/types'

import { NewTaskDialog } from './NewTaskDialog'

/**
 * Run: make a task for the agent by hand (origin `human`), then open it.
 * Hidden without `agent_task:create` or when the agent is disabled.
 */
export function RunTaskButton({ agent }: { agent: Agent }) {
  const canCreate = useHasPermission(
    'agent_task:create',
    agent.organization.slug,
  )
  const [open, setOpen] = useState(false)
  if (!canCreate || !agent.enabled) return null
  return (
    <>
      <Button onClick={() => setOpen(true)} size="sm" variant="outline">
        <Play className="mr-2 size-4" />
        Run
      </Button>
      <NewTaskDialog
        agent={agent}
        isOpen={open}
        onClose={() => setOpen(false)}
      />
    </>
  )
}
