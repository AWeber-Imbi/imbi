import { ApiError } from '@/api/client'
import {
  createAgent,
  createPrompt,
  createPromptVersion,
  setPromptLabel,
  updateAgent,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { Agent, PromptVersion } from '@/types'

import {
  AGENT_PROMPT_LABEL,
  AGENT_PROMPT_NAMESPACE,
  type AgentDraft,
  agentPromptRef,
  isPromptChanged,
  parsePromptRef,
  promptVersionBody,
  settingsFromDraft,
  versionSummary,
} from './agentDraft'

export interface SaveAgentArgs {
  /**
   * The prompt version that the editor started from, if any. For a new
   * agent it is the version of the agent that is copied.
   */
  baseline: null | PromptVersion
  draft: AgentDraft
  /** The stored agent, or null for a new agent. */
  existing: Agent | null
  orgSlug: string
}

export interface SaveAgentResult {
  agent: Agent
  /** The prompt version that `stable` now points at, if this save wrote one. */
  promptVersion: null | number
}

export type SaveStep = 'agent' | 'prompt-label' | 'prompt-version'

/**
 * A save failed at `step`. `promptVersion` is set when a prompt version
 * was written before the failure, so the message can say so.
 */
export class AgentSaveError extends Error {
  readonly cause: unknown
  readonly promptVersion: null | number
  readonly step: SaveStep

  constructor(step: SaveStep, cause: unknown, promptVersion: null | number) {
    super(saveErrorMessage(step, cause, promptVersion))
    this.name = 'AgentSaveError'
    this.step = step
    this.cause = cause
    this.promptVersion = promptVersion
  }
}

/**
 * Save the editor draft. When the system prompt, the model, or a model
 * parameter changed, write a new prompt version (create the prompt if
 * it does not exist), then move the `stable` label to it. Then create or
 * update the agent with `prompt_ref` set to `<namespace>/<slug>@stable`
 * and `prompt_version` set to the new version, so that one save writes
 * one agent version that records both.
 *
 * When the prompt did not change, `prompt_version` stays as it is. An
 * agent saved before `prompt_version` existed has none; it then gets
 * the number of the version that the editor loaded.
 *
 * Each step runs only when the step before it succeeded. A failure
 * throws AgentSaveError with the step that failed.
 */
export async function saveAgent({
  baseline,
  draft,
  existing,
  orgSlug,
}: SaveAgentArgs): Promise<SaveAgentResult> {
  const target = (existing?.prompt_ref &&
    parsePromptRef(existing.prompt_ref)) || {
    namespace: AGENT_PROMPT_NAMESPACE,
    slug: existing?.slug ?? draft.slug,
  }
  let promptRef = existing?.prompt_ref ?? null
  let promptVersion: null | number = null

  // A new agent has no prompt yet, so any prompt content is a change.
  if (isPromptChanged(draft.prompt, existing ? baseline : null)) {
    const body = promptVersionBody(
      draft.prompt,
      baseline,
      `Saved from the ${draft.name} agent editor`,
    )
    try {
      promptVersion = await writePromptVersion(target, draft.name, body)
    } catch (error) {
      throw new AgentSaveError('prompt-version', error, null)
    }
    try {
      await setPromptLabel(
        target.namespace,
        target.slug,
        AGENT_PROMPT_LABEL,
        promptVersion,
      )
    } catch (error) {
      throw new AgentSaveError('prompt-label', error, promptVersion)
    }
    promptRef = agentPromptRef(target.namespace, target.slug)
  }

  const document = {
    description: draft.description.trim() || null,
    icon: draft.icon || null,
    name: draft.name.trim(),
    prompt_ref: promptRef,
    prompt_version: promptVersion ?? currentPromptVersion(existing, baseline),
    settings: settingsFromDraft(draft.settings),
    slack_channel: draft.slackChannel.trim() || null,
    slug: existing?.slug ?? draft.slug,
    tags: draft.tags.map((t) => t.slug),
    team: draft.team,
    version_summary: versionSummary(existing, draft, promptVersion),
  }
  try {
    const agent = existing
      ? await updateAgent(orgSlug, existing.slug, document)
      : await createAgent(orgSlug, { ...document, enabled: true })
    return { agent, promptVersion }
  } catch (error) {
    throw new AgentSaveError('agent', error, promptVersion)
  }
}

/** The prompt version that a stored agent uses now, if known. */
function currentPromptVersion(
  existing: Agent | null,
  baseline: null | PromptVersion,
): null | number {
  if (!existing?.prompt_ref) return null
  return existing.prompt_version ?? baseline?.n ?? null
}

function saveErrorMessage(
  step: SaveStep,
  cause: unknown,
  promptVersion: null | number,
): string {
  const detail = extractApiErrorDetail(cause)
  if (step === 'prompt-version')
    return `Could not save the system prompt and model to the prompt CMS: ${detail}. Nothing was saved.`
  if (step === 'prompt-label')
    return `Saved prompt version ${promptVersion}, but could not move the ${AGENT_PROMPT_LABEL} label to it: ${detail}. The agent was not saved.`
  if (promptVersion !== null)
    return `Saved prompt version ${promptVersion} and moved ${AGENT_PROMPT_LABEL} to it, but could not save the agent: ${detail}.`
  return `Could not save the agent: ${detail}.`
}

/**
 * Write a new version of the prompt and return its number. When the
 * prompt does not exist, create it; its first version is the body.
 */
async function writePromptVersion(
  target: { namespace: string; slug: string },
  agentName: string,
  body: ReturnType<typeof promptVersionBody>,
): Promise<number> {
  try {
    const version = await createPromptVersion(
      target.namespace,
      target.slug,
      body,
    )
    return version.n
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error
  }
  const prompt = await createPrompt({
    default_label: AGENT_PROMPT_LABEL,
    description: `System prompt and model for the ${agentName} agent.`,
    kind: 'generative',
    name: agentName,
    namespace: target.namespace,
    slug: target.slug,
    version: body,
  })
  return prompt.latest_version || 1
}
