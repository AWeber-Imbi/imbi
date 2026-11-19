import { useEffect, useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Box, Check, Plus, Search, X } from 'lucide-react'

import { createTicket, getProjectsSlim } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from '@/components/ui/dialog'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Input } from '@/components/ui/input'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useUserDisplayNames } from '@/hooks/useUserDisplayNames'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { Agent } from '@/types'

import { useAgentList } from './agentQueries'
import { ticketsPath } from './agentsNav'
import { detectSource, titleFrom } from './newTask'
import { type Priority, PriorityPicker } from './priority'
import { errorMessage } from './taskQueries'

const PROJECTS_SHOWN = 6

/**
 * Hand a piece of work to an agent or a person (ADR 0028), and open the
 * ticket. A runner starts a queued ticket for its agent; a person ticket
 * starts open. `agent` selects an agent first (the Run button of an
 * agent).
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
  const [request, setRequest] = useState('')
  const [agentSlug, setAgentSlug] = useState('')
  const [projectIds, setProjectIds] = useState<string[]>([])
  const [priority, setPriority] = useState<Priority>('normal')
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState<'agent' | 'person'>('agent')
  const [assignee, setAssignee] = useState('')
  const [requires, setRequires] = useState('')
  const [gates, setGates] = useState(false)
  const { users } = useUserDisplayNames()

  useEffect(() => {
    if (!isOpen) return
    setRequest('')
    setKind('agent')
    setAssignee('')
    setRequires('')
    setGates(false)
    setAgentSlug(agent?.slug ?? '')
    setProjectIds([])
    setPriority('normal')
    setQuery('')
  }, [agent, isOpen])

  // The Run button of an agent keeps its agent.
  const { data: agentList = [] } = useAgentList(
    isOpen && !agent ? orgSlug : undefined,
  )
  const agents = useMemo(
    () =>
      agent
        ? [agent]
        : agentList
            .filter((a) => a.enabled)
            .sort((a, b) => a.name.localeCompare(b.name)),
    [agent, agentList],
  )
  const { data: projectList = [] } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['projects', orgSlug, 'slim'],
  })
  const selected = projectIds
    .map((id) => projectList.find((p) => p.id === id))
    .filter((p) => !!p)
  const projects = useMemo(() => {
    const q = query.trim().toLowerCase()
    return projectList
      .filter(
        (p) =>
          !p.archived &&
          !projectIds.includes(p.id) &&
          (!q || p.slug.includes(q)),
      )
      .sort((a, b) => a.slug.localeCompare(b.slug))
      .slice(0, PROJECTS_SHOWN)
  }, [projectList, projectIds, query])

  const source = detectSource(request)
  const person = kind === 'person'
  const missing = [
    !request.trim() && 'a description',
    person ? !assignee.trim() && 'a person' : !agentSlug && 'an agent',
  ].filter((m): m is string => !!m)

  const create = useMutation({
    mutationFn: () =>
      createTicket(orgSlug, {
        ...(person
          ? { assignee: assignee.trim(), assignee_kind: 'person' }
          : { agent_slug: agentSlug, assignee_kind: 'agent' }),
        description: request.trim(),
        priority,
        project_ids: projectIds,
        requires: requires
          .split(/[\s,]+/)
          .filter(Boolean)
          .map((short_id) => ({ gates, short_id })),
        title: titleFrom(request),
      }),
    onSuccess: (task) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.tickets(orgSlug),
      })
      onClose()
      navigate(ticketsPath(orgSlug, task.short_id))
    },
  })
  const ready = missing.length === 0 && !create.isPending
  const { reset } = create
  // A reopened dialog shows no error from the last attempt.
  useEffect(() => {
    if (isOpen) reset()
  }, [isOpen, reset])

  return (
    <Dialog
      onOpenChange={(open) => !open && !create.isPending && onClose()}
      open={isOpen}
    >
      <DialogContent className="max-h-[calc(100vh-48px)] max-w-160 gap-0 overflow-hidden p-0">
        <div className="border-tertiary shrink-0 border-b px-5 pt-4.5 pr-12 pb-3.5">
          <DialogTitle className="text-[17px] font-semibold">
            New ticket
          </DialogTitle>
          <DialogDescription className="text-secondary mt-0.5 text-[12.5px]">
            Hand a piece of work to an agent or a person. It shows up in your
            Inbox as soon as you create it.
          </DialogDescription>
        </div>
        <form
          className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 pt-4.5 pb-5"
          id="new-agent-task"
          onSubmit={(e) => {
            e.preventDefault()
            if (ready) create.mutate()
          }}
        >
          <label className="flex flex-col gap-2">
            <Overline>What should be done?</Overline>
            <Textarea
              aria-label="What should be done?"
              onChange={(e) => setRequest(e.target.value)}
              placeholder="Describe the outcome you want. Paste a Sentry issue, pull request, or Slack thread link to use it as the source."
              rows={4}
              value={request}
            />
            {source && (
              <div className="border-tertiary bg-secondary flex items-center gap-2 rounded-md border px-2.5 py-1.5">
                <source.icon className="text-secondary size-3.25" />
                <span className="text-secondary text-xs">Source</span>
                <span className="text-[12.5px] font-medium">
                  {source.label}
                </span>
                <span className="text-tertiary ml-auto max-w-65 truncate font-mono text-[11.5px]">
                  {source.url}
                </span>
              </div>
            )}
          </label>

          <div className="flex flex-col items-start gap-2">
            <Overline>Assign to</Overline>
            {!agent && (
              <SegmentedControl
                ariaLabel="Assignee kind"
                onValueChange={(v) => setKind(v as 'agent' | 'person')}
                value={kind}
              >
                <SegmentedControlItem value="agent">Agent</SegmentedControlItem>
                <SegmentedControlItem value="person">
                  Person
                </SegmentedControlItem>
              </SegmentedControl>
            )}
            {person ? (
              <>
                <Input
                  aria-label="Assignee email"
                  className="h-8.5 text-[13px]"
                  list="new-ticket-assignees"
                  onChange={(e) => setAssignee(e.target.value)}
                  placeholder="person@example.com"
                  type="email"
                  value={assignee}
                />
                <datalist id="new-ticket-assignees">
                  {users.map((u) => (
                    <option key={u.email} value={u.email}>
                      {u.display_name}
                    </option>
                  ))}
                </datalist>
              </>
            ) : agents.length === 0 ? (
              <p className="text-tertiary text-sm">No enabled agents.</p>
            ) : (
              <div
                aria-label="Agent"
                className="grid grid-cols-2 gap-2"
                role="radiogroup"
              >
                {agents.map((a) => (
                  <AgentCard
                    agent={a}
                    key={a.slug}
                    onSelect={() => setAgentSlug(a.slug)}
                    selected={a.slug === agentSlug}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Overline>Requires (optional)</Overline>
            <Input
              aria-label="Required tickets"
              className="h-8.5 font-mono text-[13px]"
              onChange={(e) => setRequires(e.target.value)}
              placeholder="T-12, T-15"
              value={requires}
            />
            <label className="text-secondary flex items-center gap-2 text-[12.5px]">
              <Checkbox
                checked={gates}
                onCheckedChange={(v) => setGates(v === true)}
              />
              Hold this ticket until they are done
            </label>
          </div>

          <div className="flex flex-col items-start gap-2">
            <Overline>Priority</Overline>
            <PriorityPicker onChange={setPriority} value={priority} />
          </div>

          <div className="flex flex-col gap-2">
            <Overline>Projects (optional)</Overline>
            {selected.length > 0 && (
              <ul
                aria-label="Selected projects"
                className="flex flex-wrap gap-1.5"
              >
                {selected.map((p) => (
                  <li
                    className="border-secondary flex items-center gap-1.5 rounded-md border py-1 pr-1 pl-2"
                    key={p.id}
                  >
                    <Box className="text-secondary size-3.25" />
                    <span className="font-mono text-[12.5px] font-medium">
                      {p.slug}
                    </span>
                    <button
                      aria-label={`Remove project ${p.slug}`}
                      className="text-tertiary hover:text-primary rounded p-0.5"
                      onClick={() =>
                        setProjectIds((ids) => ids.filter((id) => id !== p.id))
                      }
                      type="button"
                    >
                      <X className="size-3" />
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="border-secondary overflow-hidden rounded-md border">
              <div className="border-tertiary bg-secondary flex h-8.5 items-center gap-2 border-b px-2.5">
                <Search className="text-tertiary size-3.5" />
                <input
                  aria-label="Search projects"
                  className="min-w-0 flex-1 bg-transparent text-[13px] outline-none"
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search projects"
                  value={query}
                />
              </div>
              {projects.map((p) => (
                <button
                  className="border-tertiary hover:bg-secondary flex w-full items-center gap-2 border-b px-3 py-2 text-left last:border-b-0"
                  key={p.id}
                  onClick={() => {
                    setProjectIds((ids) => [...ids, p.id])
                    setQuery('')
                  }}
                  type="button"
                >
                  <Box className="text-tertiary size-3.25" />
                  <span className="font-mono text-[12.5px]">{p.slug}</span>
                  <span className="text-tertiary ml-auto text-[11.5px]">
                    {p.project_types[0]?.name}
                  </span>
                </button>
              ))}
              {projects.length === 0 && (
                <p className="text-tertiary px-3 py-3 text-[12.5px]">
                  {query.trim()
                    ? `No projects match "${query.trim()}".`
                    : 'No projects.'}
                </p>
              )}
            </div>
          </div>

          {create.error && (
            <p className="text-danger text-sm" role="alert">
              {errorMessage(create.error)}
            </p>
          )}
        </form>
        <div className="border-tertiary bg-secondary flex shrink-0 items-center gap-2 border-t px-5 py-3">
          <span className="text-tertiary min-w-0 text-xs">
            {missing.length
              ? `Needs ${missing.join(', ').replace(/, ([^,]*)$/, ' and $1')}.`
              : `Starts as ${person ? 'Open' : 'Queued'}${gates && requires.trim() ? ', or Held while a prerequisite is open' : ''}. Esc to cancel.`}
          </span>
          <Button
            className="ml-auto"
            disabled={create.isPending}
            onClick={onClose}
            size="sm"
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button
            disabled={!ready}
            form="new-agent-task"
            size="sm"
            type="submit"
          >
            <Plus className="mr-1 size-3.5" />
            Create ticket
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function AgentCard({
  agent,
  onSelect,
  selected,
}: {
  agent: Agent
  onSelect: () => void
  selected: boolean
}) {
  return (
    <button
      aria-checked={selected}
      className={cn(
        'flex items-start gap-2.5 rounded-lg border bg-primary px-3 py-2.75 text-left transition-colors',
        selected
          ? 'border-(--ds-text-primary) shadow-[inset_0_0_0_1px_var(--ds-text-primary)]'
          : 'border-secondary hover:border-(--ds-border-primary)',
      )}
      onClick={onSelect}
      role="radio"
      type="button"
    >
      <span className="bg-secondary text-secondary flex size-7 shrink-0 items-center justify-center rounded-md">
        {agent.icon ? (
          <EntityIcon className="size-4" icon={agent.icon} />
        ) : (
          <span className="text-[11px] font-semibold">
            {agent.name.slice(0, 2).toUpperCase()}
          </span>
        )}
      </span>
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-center gap-1.5">
          <span className="text-[13.5px] font-semibold">{agent.name}</span>
          <span className="text-tertiary font-mono text-[11px]">
            v{agent.version}
          </span>
        </span>
        {agent.description && (
          <span className="text-secondary line-clamp-2 text-xs leading-snug">
            {agent.description}
          </span>
        )}
      </span>
      <span
        className={cn(
          'ml-auto flex size-4.5 shrink-0 items-center justify-center rounded-full border',
          selected
            ? 'border-(--ds-text-primary) bg-(--ds-text-primary) text-(--ds-bg-primary)'
            : 'border-(--ds-border-primary) text-transparent',
        )}
      >
        <Check className="size-2.75" />
      </span>
    </button>
  )
}

function Overline({ children }: { children: React.ReactNode }) {
  return (
    <span className="text-tertiary text-[11.5px] font-semibold tracking-[0.06em] uppercase">
      {children}
    </span>
  )
}
