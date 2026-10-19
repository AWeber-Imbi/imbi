import { useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { createAgentTask, getProjects } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
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
import { useOrganization } from '@/contexts/OrganizationContext'
import { queryKeys } from '@/lib/queryKeys'
import type { Agent } from '@/types'

import { useAgentList } from './agentQueries'
import { agentsPath } from './agentsNav'
import { errorMessage } from './taskQueries'

/**
 * Make a task by hand (origin `human`) and open it. A runner starts a
 * queued task for its agent; nothing else is needed. With `agent`, the
 * agent is fixed (the Run button of an agent).
 */
export function NewTaskDialog({
  agent,
  isOpen,
  onClose,
}: {
  agent?: Agent
  isOpen: boolean
  onClose: () => void
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const orgSlug = agent?.organization.slug ?? selectedOrganization?.slug ?? ''
  const [agentSlug, setAgentSlug] = useState('')
  const [projectId, setProjectId] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')

  useEffect(() => {
    if (!isOpen) return
    setAgentSlug(agent?.slug ?? '')
    setProjectId('')
    setTitle('')
    setDescription('')
  }, [agent, isOpen])

  const { data: agents = [] } = useAgentList(
    isOpen && !agent ? orgSlug : undefined,
  )
  const { data: projects = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })
  const agentOptions = useMemo(
    () =>
      agents
        .filter((a) => a.enabled)
        .map((a) => ({ label: a.name, value: a.slug }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [agents],
  )
  const projectOptions = useMemo(
    () => [
      { label: 'No project', value: '' },
      ...projects
        .map((p) => ({ label: p.name ?? p.slug, value: p.id }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    ],
    [projects],
  )

  const create = useMutation({
    mutationFn: () =>
      createAgentTask(orgSlug, {
        agent_slug: agentSlug,
        description: description.trim(),
        project_id: projectId || undefined,
        title: title.trim(),
      }),
    onSuccess: (task) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agentTasks(orgSlug),
      })
      onClose()
      navigate(agentsPath('tasks', orgSlug, task.short_id))
    },
  })
  const ready =
    !!agentSlug && !!title.trim() && !!description.trim() && !create.isPending

  return (
    <Dialog
      onOpenChange={(open) => !open && !create.isPending && onClose()}
      open={isOpen}
    >
      <DialogContent className="max-w-170">
        <DialogHeader>
          <DialogTitle>{agent ? `Run ${agent.name}` : 'New task'}</DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-4 p-6"
          id="new-agent-task"
          onSubmit={(e) => {
            e.preventDefault()
            if (ready) create.mutate()
          }}
        >
          {!agent && (
            <div className="flex flex-col gap-2">
              <Label htmlFor="new-task-agent">Agent</Label>
              <Combobox
                id="new-task-agent"
                onChange={setAgentSlug}
                options={agentOptions}
                placeholder="Select agent..."
                value={agentSlug}
              />
            </div>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-task-project">Project</Label>
            <Combobox
              id="new-task-project"
              onChange={setProjectId}
              options={projectOptions}
              placeholder="No project"
              value={projectId}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-task-title">Title</Label>
            <Input
              id="new-task-title"
              onChange={(e) => setTitle(e.target.value)}
              required
              value={title}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="new-task-instruction">Instruction</Label>
            <Textarea
              id="new-task-instruction"
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
            onClick={onClose}
            variant="outline"
          >
            Cancel
          </Button>
          <Button disabled={!ready} form="new-agent-task" type="submit">
            {agent ? 'Run' : 'Create task'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
