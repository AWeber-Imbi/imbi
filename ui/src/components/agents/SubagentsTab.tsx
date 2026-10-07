import { useState } from 'react'

import { Bot, ChevronDown, ChevronUp } from 'lucide-react'

import { Alert } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { Sk } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { useIcon } from '@/lib/icons'
import type { Agent, AgentSubagent } from '@/types'

import { useAgentList } from './agentQueries'

/** Show a search field when there are more choices than this. */
const SEARCH_THRESHOLD = 10

interface SubagentRowProps {
  agent: Agent
  isOpen: boolean
  onInstructionsChange: (instructions: string) => void
  onToggle: (checked: boolean) => void
  onToggleOpen: () => void
  selected: AgentSubagent | undefined
}

interface SubagentsTabProps {
  /** The id of the agent that is edited, or null for a new agent. */
  agentId: null | string
  onChange: (subagents: AgentSubagent[]) => void
  orgSlug: string
  /** The subagents of the saved agent. Their rows stay while you edit. */
  saved?: Pick<AgentSubagent, 'agent_id'>[]
  value: AgentSubagent[]
}

/**
 * The other agents of the org that this agent can delegate to. A
 * checked agent can have delegation instructions. A disabled agent
 * shows only when it is selected now or in the saved agent.
 */
export function SubagentsTab({
  agentId,
  onChange,
  orgSlug,
  saved = [],
  value,
}: SubagentsTabProps) {
  const agents = useAgentList(orgSlug)
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<Set<string>>(new Set())

  if (agents.isLoading)
    return (
      <div className="flex flex-col gap-3">
        <Sk h={48} r={8} />
        <Sk h={48} r={8} />
      </div>
    )
  if (agents.isError || !agents.data)
    return <ErrorBanner error={agents.error} title="Failed to load agents" />

  const byId = new Map(value.map((s) => [s.agent_id, s]))
  // Keep a saved disabled subagent after you clear it, so you can select it again.
  const savedIds = new Set(saved.map((s) => s.agent_id))
  const choices = agents.data.filter(
    (a) =>
      a.id !== agentId && (a.enabled || byId.has(a.id) || savedIds.has(a.id)),
  )
  // A stored subagent that is not in the list has no row, so do not count it.
  const selectedCount = choices.filter((a) => byId.has(a.id)).length
  const query = search.trim().toLowerCase()
  const shown = query
    ? choices.filter((a) =>
        [a.name, a.slug, a.description ?? ''].some((text) =>
          text.toLowerCase().includes(query),
        ),
      )
    : choices

  const toggle = (id: string, checked: boolean) =>
    onChange(
      checked
        ? [...value, { agent_id: id, instructions: '' }]
        : value.filter((s) => s.agent_id !== id),
    )
  const setInstructions = (id: string, instructions: string) =>
    onChange(value.map((s) => (s.agent_id === id ? { ...s, instructions } : s)))
  const toggleOpen = (id: string) =>
    setOpen((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <div className="flex flex-col gap-4">
      <p className="text-secondary text-sm">
        Imbi does not run agents yet. These settings are stored for when it
        does.
      </p>
      {/* Keep an active search visible, so you can clear it. */}
      {(choices.length > SEARCH_THRESHOLD || search !== '') && (
        <Input
          aria-label="Search agents"
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search ${choices.length} agents — name or description`}
          value={search}
        />
      )}
      <div className="border-border bg-card overflow-hidden rounded-lg border">
        <div className="border-border flex items-center justify-between border-b px-5 py-3">
          <span className="text-overline text-tertiary uppercase">
            Delegates to
          </span>
          <span className="text-secondary font-mono text-xs tabular-nums">
            {selectedCount} of {choices.length} agents
          </span>
        </div>
        {choices.length === 0 && (
          <p className="text-tertiary px-5 py-4 text-sm">
            There are no other agents in this organization.
          </p>
        )}
        {choices.length > 0 && shown.length === 0 && (
          <p className="text-tertiary px-5 py-4 text-sm">
            No agents match that search.
          </p>
        )}
        {shown.map((a) => (
          <SubagentRow
            agent={a}
            isOpen={open.has(a.id)}
            key={a.id}
            onInstructionsChange={(text) => setInstructions(a.id, text)}
            onToggle={(checked) => toggle(a.id, checked)}
            onToggleOpen={() => toggleOpen(a.id)}
            selected={byId.get(a.id)}
          />
        ))}
      </div>
      <Alert variant="info">
        Delegation depth is capped at 2. Subagents of subagents are not called.
      </Alert>
    </div>
  )
}

function SubagentRow({
  agent,
  isOpen,
  onInstructionsChange,
  onToggle,
  onToggleOpen,
  selected,
}: SubagentRowProps) {
  const Icon = useIcon(agent.icon, Bot)
  const showPrompt = !!selected && isOpen
  const Caret = showPrompt ? ChevronUp : ChevronDown
  const fieldId = `subagent-instructions-${agent.id}`
  return (
    <div className="border-border border-b last:border-b-0">
      <div className="flex items-center gap-3 px-5 py-3">
        <Checkbox
          aria-label={`Delegate to ${agent.name}`}
          checked={!!selected}
          onCheckedChange={(checked) => onToggle(checked === true)}
        />
        <Icon className="text-secondary size-4 shrink-0" />
        <span className="w-33 shrink-0 truncate text-sm font-medium">
          {agent.name}
        </span>
        <span className="text-secondary min-w-0 flex-1 truncate text-xs">
          {agent.description}
        </span>
        {!agent.enabled && <Badge variant="neutral">Disabled</Badge>}
        {selected && (
          <button
            aria-expanded={showPrompt}
            className="border-input text-secondary hover:bg-secondary flex h-7 items-center gap-1.5 rounded-md border px-2 text-xs whitespace-nowrap"
            onClick={onToggleOpen}
            type="button"
          >
            {selected.instructions ? 'Instructions set' : 'Add instructions'}
            <Caret className="size-3" />
          </button>
        )}
      </div>
      {showPrompt && (
        <div className="border-border bg-secondary border-t py-4 pr-5 pl-14">
          <label
            className="text-secondary mb-1.5 block text-sm"
            htmlFor={fieldId}
          >
            Delegation instructions for {agent.name}
          </label>
          <Textarea
            className="font-mono"
            id={fieldId}
            onChange={(e) => onInstructionsChange(e.target.value)}
            placeholder="For example: Only hand off write operations. Report the row count before running anything."
            rows={4}
            value={selected.instructions}
          />
          <p className="text-tertiary mt-1.5 text-xs">
            Appended to {agent.name}&apos;s own system prompt when this agent
            delegates to it. Leave empty to delegate with the task context
            alone.
          </p>
        </div>
      )}
    </div>
  )
}
