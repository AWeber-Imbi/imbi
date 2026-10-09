import { useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Play } from 'lucide-react'

import { createAgentTask } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { Agent } from '@/types'

import { agentsPath } from './agentsNav'
import { errorMessage } from './taskQueries'

/**
 * Run: make a task for the agent by hand (origin `human`), then open it.
 * Hidden without `agent_task:create` or when the agent is disabled.
 */
export function RunTaskButton({ agent }: { agent: Agent }) {
  const canCreate = useHasPermission('agent_task:create')
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const orgSlug = agent.organization.slug
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const create = useMutation({
    mutationFn: () =>
      createAgentTask(orgSlug, {
        agent_slug: agent.slug,
        description: description.trim(),
        title: title.trim(),
      }),
    onSuccess: (task) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agentTasks(orgSlug),
      })
      navigate(agentsPath('tasks', orgSlug, task.short_id))
    },
  })
  if (!canCreate || !agent.enabled) return null
  return (
    <>
      <Button onClick={() => setOpen(true)} size="sm" variant="outline">
        <Play className="mr-2 size-4" />
        Run
      </Button>
      <Dialog onOpenChange={(o) => !create.isPending && setOpen(o)} open={open}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Run {agent.name}</DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-4 p-6"
            id="run-agent-task"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="run-task-title">Title</Label>
              <Input
                id="run-task-title"
                onChange={(e) => setTitle(e.target.value)}
                required
                value={title}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="run-task-instruction">Instruction</Label>
              <Textarea
                id="run-task-instruction"
                onChange={(e) => setDescription(e.target.value)}
                required
                rows={5}
                value={description}
              />
            </div>
            {create.error && (
              <p className="text-danger text-sm" role="alert">
                {errorMessage(create.error)}
              </p>
            )}
          </form>
          <DialogFooter>
            <Button
              disabled={create.isPending}
              onClick={() => setOpen(false)}
              variant="outline"
            >
              Cancel
            </Button>
            <Button
              disabled={
                !title.trim() || !description.trim() || create.isPending
              }
              form="run-agent-task"
              type="submit"
            >
              Run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
