import { useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { toast } from 'sonner'

import { FormHeader } from '@/components/admin/form-header'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Sk } from '@/components/ui/skeleton'
import { formatRelativeDate } from '@/lib/formatDate'
import { queryKeys } from '@/lib/queryKeys'
import { cn, slugify } from '@/lib/utils'
import type { Agent, PromptVersion } from '@/types'

import {
  type AgentDraft,
  draftErrors,
  draftFromAgent,
  duplicateDraft,
  emptyDraft,
} from './agentDraft'
import { usePromptResolution } from './agentQueries'
import { agentsPath } from './agentsNav'
import { ModelTab } from './ModelTab'
import { OverviewTab } from './OverviewTab'
import { saveAgent } from './saveAgent'
import { SettingsTab } from './SettingsTab'
import { SubagentsTab } from './SubagentsTab'
import { SystemPromptTab } from './SystemPromptTab'
import { ToolsTab } from './ToolsTab'
import { VersionHistoryTab } from './VersionHistoryTab'

type TabKey =
  | 'model'
  | 'overview'
  | 'prompt'
  | 'settings'
  | 'subagents'
  | 'tools'
  | 'versions'

const TABS: { key: TabKey; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'prompt', label: 'System prompt' },
  { key: 'tools', label: 'Tools and MCPs' },
  { key: 'model', label: 'Model' },
  { key: 'subagents', label: 'Subagents' },
  { key: 'settings', label: 'Settings' },
  { key: 'versions', label: 'Version history' },
]

const SETTINGS_FIELDS = new Set([
  'maxConcurrentTasks',
  'monthlyCostCap',
  'taskTimeout',
])

interface AgentEditorProps {
  /** The agent to edit, or null to create one. */
  agent: Agent | null
  orgSlug: string
  /** For a new agent: the agent to copy (Duplicate). */
  source: Agent | null
}

/**
 * Create or edit an agent. The editor first loads the prompt version
 * that the agent (or the agent to copy) uses, because the system
 * prompt, the model, and the model parameters live in the prompt CMS.
 */
export function AgentEditor({ agent, orgSlug, source }: AgentEditorProps) {
  const navigate = useNavigate()
  const ref = agent?.prompt_ref ?? source?.prompt_ref
  const prompt = usePromptResolution(ref)

  if (ref && prompt.isLoading) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <Sk h={40} r={6} />
        <Sk h={320} r={8} />
      </div>
    )
  }
  if (prompt.isError) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <ErrorBanner
          error={prompt.error}
          title={`Failed to load the prompt ${ref}`}
        />
        <button
          className="text-action self-start text-sm"
          onClick={() =>
            navigate(agentsPath('manage', ...(agent ? [agent.slug] : [])))
          }
          type="button"
        >
          Back
        </button>
      </div>
    )
  }
  return (
    <AgentEditorForm
      agent={agent}
      baseline={prompt.data ?? null}
      orgSlug={orgSlug}
      source={source}
    />
  )
}

function AgentEditorForm({
  agent,
  baseline,
  orgSlug,
  source,
}: AgentEditorProps & { baseline: null | PromptVersion }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<AgentDraft>(() =>
    agent
      ? draftFromAgent(agent, baseline)
      : source
        ? duplicateDraft(source, baseline)
        : emptyDraft(),
  )
  const [tab, setTab] = useState<TabKey>('overview')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const update = (patch: Partial<AgentDraft>) =>
    setDraft((d) => ({ ...d, ...patch }))

  const save = useMutation({
    mutationFn: () => saveAgent({ baseline, draft, existing: agent, orgSlug }),
    onSuccess: ({ agent: saved }) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agents(orgSlug),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.agentVersions(orgSlug, saved.slug),
      })
      if (saved.prompt_ref)
        void queryClient.invalidateQueries({
          queryKey: queryKeys.promptResolution(saved.prompt_ref),
        })
      toast.success(agent ? `Saved ${saved.name}` : `Created ${saved.name}`)
      navigate(agentsPath('manage', saved.slug))
    },
  })

  const onSave = () => {
    const found = draftErrors(draft)
    setErrors(found)
    const first = Object.keys(found)[0]
    if (first) {
      setTab(
        first.startsWith('param.')
          ? 'model'
          : SETTINGS_FIELDS.has(first)
            ? 'settings'
            : 'overview',
      )
      return
    }
    save.mutate()
  }

  const tabs = agent ? TABS : TABS.filter((t) => t.key !== 'versions')

  return (
    <div className="flex flex-col gap-6 p-8">
      <FormHeader
        createLabel="Create Agent"
        isEditing={!!agent}
        isLoading={save.isPending}
        onCancel={() =>
          navigate(agentsPath('manage', ...(agent ? [agent.slug] : [])))
        }
        onSave={onSave}
        subtitle={
          agent
            ? `v${agent.version} · edited ${formatRelativeDate(agent.last_version_at ?? agent.updated_at)}${agent.updated_by ? ` by ${agent.updated_by}` : ''}`
            : 'Draft — not saved yet'
        }
        title={agent ? `Edit ${agent.name}` : 'New Agent'}
      />

      {save.error && (
        <div
          className="border-danger bg-danger text-danger flex items-start gap-3 rounded-lg border p-4"
          role="alert"
        >
          <AlertCircle className="size-5 shrink-0" />
          <div>
            <div className="font-medium">Save failed</div>
            <div className="mt-1 text-sm">{save.error.message}</div>
          </div>
        </div>
      )}

      <div className="border-border flex gap-1 border-b" role="tablist">
        {tabs.map((t) => (
          <button
            aria-selected={tab === t.key}
            className={cn(
              '-mb-px border-b-2 px-4 py-2.5 text-sm whitespace-nowrap',
              tab === t.key
                ? 'border-action font-medium text-primary'
                : 'border-transparent text-secondary hover:text-primary',
            )}
            key={t.key}
            onClick={() => setTab(t.key)}
            role="tab"
            type="button"
          >
            {t.label}
            {(t.key === 'tools' || t.key === 'subagents') && (
              <span className="text-tertiary ml-2 font-mono text-xs tabular-nums">
                {t.key === 'tools'
                  ? Object.keys(draft.tools).length
                  : draft.subagents.length}
              </span>
            )}
          </button>
        ))}
      </div>

      {tab === 'overview' && (
        <OverviewTab
          draft={draft}
          errors={errors}
          onChange={update}
          onNameChange={(name) =>
            update(agent ? { name } : { name, slug: slugify(name) })
          }
          orgSlug={orgSlug}
        />
      )}
      {tab === 'prompt' && (
        <SystemPromptTab
          onChange={(system) => update({ prompt: { ...draft.prompt, system } })}
          value={draft.prompt.system}
        />
      )}
      {tab === 'tools' && (
        <ToolsTab
          onChange={(tools) => update({ tools })}
          orgSlug={orgSlug}
          value={draft.tools}
        />
      )}
      {tab === 'model' && (
        <ModelTab
          errors={errors}
          onChange={(prompt) => update({ prompt })}
          value={draft.prompt}
        />
      )}
      {tab === 'subagents' && (
        <SubagentsTab
          agentId={agent?.id ?? null}
          onChange={(subagents) => update({ subagents })}
          orgSlug={orgSlug}
          value={draft.subagents}
        />
      )}
      {tab === 'settings' && (
        <SettingsTab
          errors={errors}
          onChange={(settings) => update({ settings })}
          value={draft.settings}
        />
      )}
      {tab === 'versions' && agent && (
        <VersionHistoryTab agent={agent} orgSlug={orgSlug} />
      )}
    </div>
  )
}
