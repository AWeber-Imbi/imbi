import { slugify } from '@/lib/utils'
import type {
  Agent,
  AgentSettings,
  AgentSubagent,
  AgentToolConfig,
  PromptParams,
  PromptVersion,
  PromptVersionCreate,
} from '@/types'

// The editor state of one agent, and the conversions between that state,
// the agent API, and the prompt CMS. The model and its parameters are
// stored only in the prompt CMS; the agent keeps a `prompt_ref`.

export interface AgentDraft {
  description: string
  icon: string
  name: string
  prompt: PromptDraft
  settings: SettingsDraft
  slackChannel: string
  slug: string
  /** The agents that this agent can delegate to, in order. */
  subagents: AgentSubagent[]
  tags: AgentTagChip[]
  team: string
  /** The enabled tools, by tool key. A tool that is not here is off. */
  tools: AgentTools
}

export type AgentTagChip = Agent['tags'][number]

export type AgentTools = Record<string, AgentToolConfig>

export type ParamKey =
  | 'maxTokens'
  | 'promptCaching'
  | 'temperature'
  | 'thinking'
  | 'topK'
  | 'topP'

export interface ParamState {
  on: boolean
  value: string
}

export interface PromptDraft {
  model: null | string
  params: Record<ParamKey, ParamState>
  system: string
}

export type ResponseSla = NonNullable<AgentSettings['response_sla']>

export interface SettingsDraft {
  maxConcurrentTasks: string
  monthlyCostCap: string
  responseSla: '' | ResponseSla
  taskBudget: string
  taskTimeout: string
}

export const AGENT_PROMPT_NAMESPACE = 'agents'
export const AGENT_PROMPT_LABEL = 'stable'

// The prompt version `params` key for each editor control. `max_tokens`,
// `temperature`, and `top_p` are PromptParams fields. The others are
// pass-through keys: PromptParams accepts extra keys.
export const PARAM_FIELDS: Record<ParamKey, string> = {
  maxTokens: 'max_tokens',
  promptCaching: 'prompt_cache_ttl',
  temperature: 'temperature',
  thinking: 'thinking_budget',
  topK: 'top_k',
  topP: 'top_p',
}

// The select value for "Off" (Radix Select cannot use an empty value).
export const PARAM_OFF = 'off'

const INTEGER_PARAMS = new Set<ParamKey>(['maxTokens', 'thinking', 'topK'])
const NUMBER_PARAMS = new Set<ParamKey>(['temperature', 'topP'])

// The value a control shows when it is first switched on.
const PARAM_DEFAULTS: Record<ParamKey, string> = {
  maxTokens: '8192',
  promptCaching: '5m',
  temperature: '1',
  thinking: '4096',
  topK: '40',
  topP: '1',
}

export const SLA_OPTIONS: { label: string; value: ResponseSla }[] = [
  { label: '4 hours', value: '4h' },
  { label: '8 business hours', value: '8h' },
  { label: '24 hours', value: '24h' },
  { label: '3 days', value: '3d' },
  { label: 'No SLA', value: 'none' },
]

export function agentPromptRef(namespace: string, slug: string): string {
  return `${namespace}/${slug}@${AGENT_PROMPT_LABEL}`
}

/** Return a field-name to message map. An empty map means valid. */
export function draftErrors(draft: AgentDraft): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!draft.name.trim()) errors.name = 'Agent name is required'
  if (!draft.slug) errors.name = errors.name ?? 'Name must contain a letter'
  if (!draft.team) errors.team = 'Owner team is required'
  const s = draft.settings
  if (s.monthlyCostCap.trim() && parseMoney(s.monthlyCostCap) === null)
    errors.monthlyCostCap = 'Enter an amount, for example $400'
  if (s.taskBudget.trim() && parseMoney(s.taskBudget) === null)
    errors.taskBudget = 'Enter an amount, for example $5'
  if (s.maxConcurrentTasks.trim() && !/^[1-9]\d*$/.test(s.maxConcurrentTasks))
    errors.maxConcurrentTasks = 'Enter a whole number above 0'
  if (s.taskTimeout.trim() && parseDuration(s.taskTimeout) === null)
    errors.taskTimeout = 'Enter a duration, for example 30m or 2h'
  for (const key of Object.keys(PARAM_FIELDS) as ParamKey[]) {
    const p = draft.prompt.params[key]
    if (!p.on || p.value === PARAM_OFF) continue
    if (INTEGER_PARAMS.has(key) && !/^[1-9]\d*$/.test(p.value))
      errors[`param.${key}`] = 'Enter a whole number above 0'
    if (NUMBER_PARAMS.has(key) && !Number.isFinite(Number(p.value)))
      errors[`param.${key}`] = 'Enter a number'
  }
  return errors
}

export function draftFromAgent(
  agent: Agent,
  prompt: null | PromptVersion,
): AgentDraft {
  const settings = agent.settings ?? {}
  return {
    description: agent.description ?? '',
    icon: agent.icon ?? '',
    name: agent.name,
    prompt: promptDraftFromVersion(prompt),
    settings: {
      maxConcurrentTasks:
        settings.max_concurrent_tasks == null
          ? ''
          : String(settings.max_concurrent_tasks),
      monthlyCostCap:
        settings.monthly_cost_cap == null
          ? ''
          : formatMoney(settings.monthly_cost_cap),
      responseSla: settings.response_sla ?? '',
      taskBudget:
        settings.task_budget == null ? '' : formatMoney(settings.task_budget),
      taskTimeout:
        settings.task_timeout_seconds == null
          ? ''
          : formatDuration(settings.task_timeout_seconds),
    },
    slackChannel: agent.slack_channel ?? '',
    slug: agent.slug,
    subagents: (agent.subagents ?? []).map((s) => ({
      agent_id: s.agent_id,
      instructions: s.instructions ?? '',
    })),
    tags: agent.tags,
    team: agent.team?.slug ?? '',
    tools: agent.tools ?? {},
  }
}

/** A new-agent draft that copies `source`, named "<name> copy". */
export function duplicateDraft(
  source: Agent,
  prompt: null | PromptVersion,
): AgentDraft {
  const name = `${source.name} copy`
  return { ...draftFromAgent(source, prompt), name, slug: slugify(name) }
}

export function emptyDraft(): AgentDraft {
  return {
    description: '',
    icon: '',
    name: '',
    prompt: promptDraftFromVersion(null),
    settings: {
      maxConcurrentTasks: '',
      monthlyCostCap: '',
      responseSla: '',
      taskBudget: '',
      taskTimeout: '',
    },
    slackChannel: '',
    slug: '',
    subagents: [],
    tags: [],
    team: '',
    tools: {},
  }
}

/** Format seconds as the short form the editor reads back: 90m, 2h. */
export function formatDuration(seconds: number): string {
  if (seconds % 86400 === 0) return `${seconds / 86400}d`
  if (seconds % 3600 === 0) return `${seconds / 3600}h`
  if (seconds % 60 === 0) return `${seconds / 60}m`
  return `${seconds}s`
}

export function formatMoney(value: number | string): string {
  const n = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(n)) return String(value)
  return `$${n.toLocaleString('en-US', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2,
  })}`
}

export function isPromptChanged(
  draft: PromptDraft,
  baseline: null | PromptVersion,
): boolean {
  const before = promptDraftFromVersion(baseline)
  return (
    draft.system !== before.system ||
    (draft.model ?? null) !== (before.model ?? null) ||
    JSON.stringify(managedParams(draft.params)) !==
      JSON.stringify(managedParams(before.params))
  )
}

/** The params keys that the editor controls, from the draft. */
export function managedParams(
  params: Record<ParamKey, ParamState>,
): Record<string, number | string> {
  const out: Record<string, number | string> = {}
  for (const key of Object.keys(PARAM_FIELDS).sort() as ParamKey[]) {
    const p = params[key]
    if (!p.on || p.value.trim() === '' || p.value === PARAM_OFF) continue
    out[PARAM_FIELDS[key]] =
      INTEGER_PARAMS.has(key) || NUMBER_PARAMS.has(key)
        ? Number(p.value)
        : p.value
  }
  return out
}

/**
 * The tools in the form that the API stores: keys and environments in
 * sort order, and every field set. Two equal configurations give the
 * same JSON.
 */
export function normalizeTools(tools: AgentTools): AgentTools {
  const out: AgentTools = {}
  for (const key of Object.keys(tools).sort()) {
    const config = tools[key]
    out[key] = {
      approval: !!config.approval,
      environments: config.environments
        ? [...new Set(config.environments)].sort()
        : null,
      rate_limit: config.rate_limit ?? null,
    }
  }
  return out
}

/** Parse "30m", "2h", "1d", "45s"; a number with no unit is minutes. */
export function parseDuration(value: string): null | number {
  const match = /^\s*(\d+)\s*([smhd]?)\s*$/i.exec(value)
  if (!match) return null
  const n = Number(match[1])
  if (n <= 0) return null
  const unit = match[2].toLowerCase() || 'm'
  const factor = { d: 86400, h: 3600, m: 60, s: 1 }[unit] ?? 60
  return n * factor
}

/** Parse "$1,200.50" to "1200.50"; return null when it is not money. */
export function parseMoney(value: string): null | string {
  const cleaned = value.replace(/[$,\s]/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(cleaned)) return null
  return cleaned
}

/** Split `namespace/slug@label` into the prompt address. */
export function parsePromptRef(
  ref: string,
): null | { namespace: string; slug: string } {
  const match = /^([^/@]+)\/([^/@]+)(?:@.+)?$/.exec(ref)
  return match ? { namespace: match[1], slug: match[2] } : null
}

export function promptDraftFromVersion(
  version: null | PromptVersion,
): PromptDraft {
  const raw = (version?.params ?? {}) as Record<string, unknown>
  const params = {} as Record<ParamKey, ParamState>
  for (const key of Object.keys(PARAM_FIELDS) as ParamKey[]) {
    const stored = raw[PARAM_FIELDS[key]]
    params[key] =
      stored == null
        ? { on: false, value: PARAM_DEFAULTS[key] }
        : { on: true, value: String(stored) }
  }
  return {
    model: version?.model ?? null,
    params,
    system: version?.system ?? '',
  }
}

/**
 * The body of the new prompt version. Fields that the agent editor does
 * not show (messages, tools, variables, other params) come from the
 * baseline version, so a save from here does not remove them.
 */
export function promptVersionBody(
  draft: PromptDraft,
  baseline: null | PromptVersion,
  summary: string,
): PromptVersionCreate {
  const kept = { ...(baseline?.params ?? {}) } as Record<string, unknown>
  for (const field of Object.values(PARAM_FIELDS)) delete kept[field]
  const params = {
    ...kept,
    ...managedParams(draft.params),
    stop_sequences: baseline?.params?.stop_sequences ?? [],
  } as PromptParams
  return {
    messages: baseline?.messages ?? [],
    model: draft.model,
    params,
    questions: {},
    state: '',
    summary,
    system: draft.system,
    tools: baseline?.tools ?? [],
    variable_schema: baseline?.variable_schema ?? {},
  }
}

export function settingsFromDraft(draft: SettingsDraft): AgentSettings {
  const cap = draft.monthlyCostCap.trim()
    ? parseMoney(draft.monthlyCostCap)
    : null
  return {
    max_concurrent_tasks: draft.maxConcurrentTasks.trim()
      ? Number(draft.maxConcurrentTasks)
      : null,
    monthly_cost_cap: cap,
    response_sla: draft.responseSla || null,
    task_budget: draft.taskBudget.trim() ? parseMoney(draft.taskBudget) : null,
    task_timeout_seconds: draft.taskTimeout.trim()
      ? parseDuration(draft.taskTimeout)
      : null,
  }
}

export function slaLabel(value: null | string | undefined): null | string {
  return SLA_OPTIONS.find((o) => o.value === value)?.label ?? null
}

/** Say in words what a save changes, for the agent version note. */
export function versionSummary(
  existing: Agent | null,
  draft: AgentDraft,
  promptVersion: null | number,
): string {
  if (!existing) return 'Created the agent'
  const before = draftFromAgent(existing, null)
  const changed: string[] = []
  if (before.name !== draft.name) changed.push('name')
  if (before.description !== draft.description) changed.push('description')
  if (before.icon !== draft.icon) changed.push('icon')
  if (before.slackChannel !== draft.slackChannel) changed.push('Slack channel')
  if (before.team !== draft.team) changed.push('owner team')
  if (
    before.tags
      .map((t) => t.slug)
      .sort()
      .join() !==
    draft.tags
      .map((t) => t.slug)
      .sort()
      .join()
  )
    changed.push('labels')
  if (
    JSON.stringify(settingsFromDraft(before.settings)) !==
    JSON.stringify(settingsFromDraft(draft.settings))
  )
    changed.push('settings')
  if (
    JSON.stringify(normalizeTools(before.tools)) !==
    JSON.stringify(normalizeTools(draft.tools))
  )
    changed.push('tools')
  if (
    JSON.stringify(before.subagents) !==
    JSON.stringify(
      draft.subagents.map((s) => ({
        agent_id: s.agent_id,
        instructions: s.instructions,
      })),
    )
  )
    changed.push('subagents')
  const parts: string[] = []
  if (changed.length) parts.push(`Changed ${changed.join(', ')}`)
  if (promptVersion !== null) parts.push(`prompt v${promptVersion}`)
  return parts.length ? parts.join('; ') : 'Saved'
}

export function wordCount(text: string): number {
  return text.split(/\s+/).filter(Boolean).length
}
