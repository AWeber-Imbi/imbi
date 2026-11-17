import { ApiError } from '@/api/client'
import {
  createPrompt,
  createPromptVersion,
  createWorkflow,
  resolvePrompt,
  updateWorkflow,
} from '@/api/endpoints'
import type { PromptVersion, PromptVersionCreate } from '@/types'

import { isRecord } from './schemaFields'
import type {
  Workflow,
  WorkflowGraph,
  WorkflowNode,
  WorkflowWrite,
} from './types'

// The prompt of an LLM Call step lives in the Prompt CMS, at
// `workflows/<org>.<workflow>.<node key>`. The step pins one version
// (`prompt_ref` + `prompt_version`). The editor keeps the prompt text,
// the model, and its params here until the workflow is saved.

export const LLM_CALL = 'llm_call'
export const NAMESPACE = 'workflows'

/** The part of an LLM Call step that is stored in the CMS. */
export interface StepPrompt {
  max_tokens: null | number
  model: null | string
  /**
   * The pinned version that the draft starts from. A save keeps the
   * fields that the panel does not edit, such as other messages, stop
   * sequences, and `top_p`.
   */
  pinned?: PromptVersion
  system: string
  temperature: null | number
  user: string
}

export const EMPTY_PROMPT: StepPrompt = {
  max_tokens: null,
  model: null,
  system: '',
  temperature: null,
  user: '',
}

/** The pins that a save gives to each LLM Call node, by node id. */
type Pins = Record<string, { prompt_ref: string; prompt_version: number }>

export function draftFromVersion(version: PromptVersion): StepPrompt {
  return {
    max_tokens: version.params?.max_tokens ?? null,
    model: version.model ?? null,
    pinned: version,
    system: version.system,
    temperature: version.params?.temperature ?? null,
    user: version.messages.find((m) => m.role === 'user')?.content ?? '',
  }
}

/**
 * Create the prompt of a node when it does not exist, with the draft
 * as version 1. A run of a draft needs the prompt to exist.
 */
export async function ensurePrompt(
  slug: string,
  name: string,
  version: PromptVersionCreate,
): Promise<void> {
  try {
    await createNodePrompt(slug, name, version)
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 409) throw error
  }
}

/** The pinned `ref@n` of a node, or null when it has no prompt yet. */
export function pinnedRef(node: WorkflowNode): null | string {
  const { prompt_ref: ref, prompt_version: n } = node.params
  return typeof ref === 'string' && typeof n === 'number' ? `${ref}@${n}` : null
}

/** Put the pins of a save into the graph's LLM Call nodes. */
export function pinNodes(graph: WorkflowGraph, pins: Pins): WorkflowGraph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) =>
      pins[n.id] ? { ...n, params: { ...n.params, ...pins[n.id] } } : n,
    ),
  }
}

/** The CMS version of a draft. Its variables are the step's inputs. */
export function promptContent(
  draft: StepPrompt,
  inputs: unknown,
): Omit<PromptVersionCreate, 'summary'> {
  const base = draft.pinned
  return {
    messages: withUser(base?.messages ?? [], draft.user),
    model: draft.model,
    params: {
      stop_sequences: [],
      ...base?.params,
      max_tokens: draft.max_tokens,
      temperature: draft.temperature,
    },
    questions: base?.questions ?? {},
    state: base?.state ?? '',
    system: draft.system,
    tools: base?.tools ?? [],
    variable_schema: variableSchema(inputs),
  }
}

export function promptSlug(orgSlug: string, workflowSlug: string, key: string) {
  return `${orgSlug}.${workflowSlug}.${key}`
}

/**
 * Save a workflow. First write the CMS prompt of each LLM Call node,
 * then save the workflow with the version numbers that the CMS gave:
 * the API refuses a pin to a version that does not exist.
 *
 * A new workflow is created first, with no pins (the API does not
 * check an LLM Call node that has no pin), because the prompt slugs
 * use the slug that the API gives it. `onCreated` gets the new
 * workflow, also when a later step fails.
 */
export async function saveWorkflow(
  orgSlug: string,
  slug: string | undefined,
  draft: WorkflowWrite,
  prompts: Record<string, StepPrompt>,
  onCreated?: (created: Workflow) => void,
): Promise<{ pins: Pins; saved: Workflow }> {
  const llmCalls = draft.graph.nodes.filter((n) => n.type === LLM_CALL)
  if (!slug) {
    const created = await createWorkflow(orgSlug, {
      ...draft,
      graph: unpinNodes(draft.graph),
    })
    onCreated?.(created)
    if (!llmCalls.length) return { pins: {}, saved: created }
    slug = created.slug
  }
  const workflowSlug = slug
  const pins: Pins = {}
  // The nodes do not depend on each other: write their prompts at once.
  await Promise.all(
    llmCalls.map(async (node) => {
      const slug = promptSlug(orgSlug, workflowSlug, node.key)
      const ref = `${NAMESPACE}/${slug}`
      const pinned = pinnedRef(node)
      const draftPrompt = prompts[node.id]
      let content: Omit<PromptVersionCreate, 'summary'>
      if (draftPrompt) {
        content = promptContent(draftPrompt, node.params.inputs)
      } else {
        if (!pinned) return
        const { version } = await resolvePrompt(pinned)
        // An unchanged prompt that is already the node's own needs no
        // write, unless the step's inputs no longer match its variables.
        if (
          node.params.prompt_ref === ref &&
          sameNames(version.variable_schema, node.params.inputs)
        )
          return
        // A copied node, a new key, or changed inputs: copy the full
        // pinned version, with only its variables changed.
        content = {
          messages: version.messages,
          model: version.model,
          params: version.params,
          questions: version.questions,
          state: version.state,
          system: version.system,
          tools: version.tools,
          variable_schema: variableSchema(node.params.inputs),
        }
      }
      pins[node.id] = {
        prompt_ref: ref,
        prompt_version: await writePrompt(
          slug,
          `${draft.name} / ${node.title}`,
          node,
          content,
        ),
      }
    }),
  )
  const body = { ...draft, graph: pinNodes(draft.graph, pins) }
  return { pins, saved: await updateWorkflow(orgSlug, workflowSlug, body) }
}

function createNodePrompt(
  slug: string,
  name: string,
  version: PromptVersionCreate,
) {
  return createPrompt({
    default_label: 'stable',
    kind: 'generative',
    name,
    namespace: NAMESPACE,
    slug,
    version,
  })
}

/** Whether the variables of a version are the step's input names. */
function sameNames(schema: object, inputs: unknown): boolean {
  const names = Object.keys(isRecord(inputs) ? inputs : {})
  const vars = Object.keys(schema)
  return (
    names.length === vars.length &&
    names.every((n) => Object.prototype.hasOwnProperty.call(schema, n))
  )
}

/** Remove the pins of the graph's LLM Call nodes. */
function unpinNodes(graph: WorkflowGraph): WorkflowGraph {
  return {
    ...graph,
    nodes: graph.nodes.map((n) =>
      n.type === LLM_CALL
        ? {
            ...n,
            params: Object.fromEntries(
              Object.entries(n.params).filter(
                ([k]) => k !== 'prompt_ref' && k !== 'prompt_version',
              ),
            ),
          }
        : n,
    ),
  }
}

/** The prompt variables of a step: one for each input name. */
function variableSchema(
  inputs: unknown,
): PromptVersionCreate['variable_schema'] {
  return Object.fromEntries(
    Object.keys(isRecord(inputs) ? inputs : {}).map((name) => [
      name,
      { required: true, type: 'any' as const },
    ]),
  )
}

/** The messages with the first `user` message set to `user`. */
function withUser(
  messages: PromptVersion['messages'],
  user: string,
): PromptVersion['messages'] {
  const i = messages.findIndex((m) => m.role === 'user')
  if (i < 0) return [...messages, { content: user, role: 'user' }]
  return messages.map((m, j) => (j === i ? { ...m, content: user } : m))
}

/**
 * Write one node's prompt and return the version number to pin. A new
 * version of an existing prompt is always sent: it returns the newest
 * version when nothing changed, and it restores an archived prompt of
 * a node key that is used again.
 */
async function writePrompt(
  slug: string,
  name: string,
  node: WorkflowNode,
  content: Omit<PromptVersionCreate, 'summary'>,
): Promise<number> {
  if (!content.model) throw new Error(`Step '${node.key}': choose a model.`)
  const version = { ...content, summary: 'Saved from the workflow editor.' }
  try {
    return (await createPromptVersion(NAMESPACE, slug, version)).n
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error
  }
  return (await createNodePrompt(slug, name, version)).latest_version || 1
}
