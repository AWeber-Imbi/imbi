import type { ReactNode } from 'react'

import { useNavigate } from 'react-router-dom'

import { ArrowLeft, Bot } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { MarkdownPreview } from '@/components/ui/markdown-editor/MarkdownPreview'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useIcon } from '@/lib/icons'
import type { Agent } from '@/types'

import { formatDuration, formatMoney, slaLabel, wordCount } from './agentDraft'
import { AgentLabels } from './AgentLabelChip'
import { usePromptResolution } from './agentQueries'
import { agentsPath } from './agentsNav'

export function AgentDetail({ agent }: { agent: Agent }) {
  const navigate = useNavigate()
  const canCreate = useHasPermission('agent:create')
  const canWrite = useHasPermission('agent:write')
  const Icon = useIcon(agent.icon, Bot)
  const prompt = usePromptResolution(agent.prompt_ref)
  const version = prompt.data ?? null
  const settings = agent.settings ?? {}

  const model = prompt.isLoading
    ? '…'
    : prompt.isError
      ? 'Could not load'
      : (version?.model ?? 'Not set')

  const rows: { mono?: boolean; name: string; value: ReactNode }[] = [
    { name: 'Owner team', value: agent.team?.name ?? '—' },
    { mono: true, name: 'Model', value: model },
    { name: 'Slack channel', value: agent.slack_channel || '—' },
    {
      mono: true,
      name: 'Monthly cost cap',
      value:
        settings.monthly_cost_cap == null
          ? 'No cap'
          : formatMoney(settings.monthly_cost_cap),
    },
    {
      mono: true,
      name: 'Max concurrent tasks',
      value: settings.max_concurrent_tasks ?? 'No limit',
    },
    {
      mono: true,
      name: 'Task timeout',
      value:
        settings.task_timeout_seconds == null
          ? 'No limit'
          : formatDuration(settings.task_timeout_seconds),
    },
    {
      name: 'Human response SLA',
      value: slaLabel(settings.response_sla) ?? 'Not set',
    },
    { name: 'Labels', value: <AgentLabels tags={agent.tags} /> },
  ]

  const system = version?.system ?? ''

  return (
    <div className="flex flex-col gap-6 p-8">
      <div>
        <Button
          onClick={() => navigate(agentsPath('manage'))}
          size="sm"
          variant="outline"
        >
          <ArrowLeft className="mr-2 size-4" />
          Back to agents
        </Button>
      </div>

      <div className="flex items-start gap-4">
        <div className="bg-secondary text-action flex size-12 shrink-0 items-center justify-center rounded-lg">
          <Icon className="size-6" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-3">
            <h2 className="text-h2">{agent.name}</h2>
            <Badge variant={agent.enabled ? 'success' : 'neutral'}>
              {agent.enabled ? 'Enabled' : 'Disabled'}
            </Badge>
            <span className="text-tertiary font-mono text-sm tabular-nums">
              v{agent.version}
            </span>
          </div>
          {agent.description && (
            <p className="text-secondary mt-1 text-sm text-pretty">
              {agent.description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 gap-2">
          {canCreate && (
            <Button
              onClick={() =>
                navigate(
                  `${agentsPath('manage', 'new')}?from=${encodeURIComponent(agent.slug)}`,
                )
              }
              size="sm"
              variant="outline"
            >
              Duplicate
            </Button>
          )}
          {canWrite && (
            <Button
              onClick={() => navigate(agentsPath('manage', agent.slug, 'edit'))}
              size="sm"
            >
              Edit
            </Button>
          )}
        </div>
      </div>

      <div className="border-border bg-card rounded-lg border">
        <dl className="grid grid-cols-3 gap-x-8 gap-y-5 p-6">
          {rows.map((row) => (
            <div className="flex flex-col gap-1" key={row.name}>
              <dt className="text-overline text-tertiary uppercase">
                {row.name}
              </dt>
              <dd className={row.mono ? 'font-mono text-sm' : 'text-sm'}>
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <div className="border-border bg-card rounded-lg border">
        <div className="border-border flex items-center justify-between border-b px-6 py-4">
          <h3 className="text-card-title">System prompt</h3>
          {system && (
            <span className="text-tertiary font-mono text-sm tabular-nums">
              {wordCount(system).toLocaleString()} words
            </span>
          )}
        </div>
        <div className="max-h-65 overflow-hidden px-6 py-4">
          {prompt.isLoading ? (
            <p className="text-tertiary text-sm">Loading…</p>
          ) : system ? (
            <MarkdownPreview value={system} />
          ) : (
            <p className="text-tertiary text-sm">
              {prompt.isError
                ? 'Could not load the system prompt.'
                : 'No system prompt yet.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
