import { ApiError } from '@/api/client'
import {
  createPrompt,
  createPromptVersion,
  createWorkflow,
  resolvePrompt,
  updateWorkflow,
} from '@/api/endpoints'
import { slugify } from '@/lib/utils'
import type { PromptVersion, PromptVersionCreate } from '@/types'

import { isRecord } from './schemaFields'
import type {
  Workflow,
  WorkflowGraph,
  WorkflowNode,
  WorkflowWrite,
} from './types'

// The prompt of an analysis step lives in the Prompt CMS, at
// `workflows/<org>.<workflow>.<node key>`. The step pins one version
// (`prompt_ref` + `prompt_version`). The editor keeps the prompt text,
// the model, and its params here until the workflow is saved.

export const ANALYSIS = 'analysis'
export const NAMESPACE = 'workflows'

/** The part of an analysis step that is stored in the CMS. */
export interface StepPrompt {
  max_tokens: null | number
  model: null | string
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

/** The pins that a save gives to each analysis node, by node id. */
type Pins = Record<string, { prompt_ref: string; prompt_version: number }>

export function draftFromVersion(version: PromptVersion): StepPrompt {
  return {
    max_tokens: version.params?.max_tokens ?? null,
    model: version.model ?? null,
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

/** Put the pins of a save into the graph's analysis nodes. */
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
  return {
    messages: [{ content: draft.user, role: 'user' }],
    model: draft.model,
    params: {
      max_tokens: draft.max_tokens,
      stop_sequences: [],
      temperature: draft.temperature,
    },
    questions: {},
    state: '',
    system: draft.system,
    tools: [],
    variable_schema: Object.fromEntries(
      Object.keys(isRecord(inputs) ? inputs : {}).map((name) => [
        name,
        { required: true, type: 'str' as const },
      ]),
    ),
  }
}

export function promptSlug(orgSlug: string, workflowSlug: string, key: string) {
  return `${orgSlug}.${workflowSlug}.${key}`
}

/**
 * Save a workflow. First write the CMS prompt of each analysis node,
 * then save the workflow with the version numbers that the CMS gave:
 * the API refuses a pin to a version that does not exist.
 */
export async function saveWorkflow(
  orgSlug: string,
  slug: string | undefined,
  draft: WorkflowWrite,
  prompts: Record<string, StepPrompt>,
): Promise<{ pins: Pins; saved: Workflow }> {
  const analysis = draft.graph.nodes.filter((n) => n.type === ANALYSIS)
  // A new workflow has no slug yet; the prompt slugs need one.
  const workflowSlug = slug ?? slugify(draft.name)
  const pins: Pins = {}
  // The nodes do not depend on each other: write their prompts at once.
  await Promise.all(
    analysis.map(async (node) => {
      const slug = promptSlug(orgSlug, workflowSlug, node.key)
      const ref = `${NAMESPACE}/${slug}`
      const pinned = pinnedRef(node)
      // An unchanged prompt that is already the node's own needs no write.
      if (!prompts[node.id] && (!pinned || node.params.prompt_ref === ref))
        return
      const content =
        prompts[node.id] ??
        // A copied node or a new key: copy the content of the old pin.
        draftFromVersion((await resolvePrompt(pinned!)).version)
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
  const saved = slug
    ? await updateWorkflow(orgSlug, slug, body)
    : await createWorkflow(
        orgSlug,
        analysis.length ? { ...body, slug: workflowSlug } : body,
      )
  return { pins, saved }
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
  draft: StepPrompt,
): Promise<number> {
  if (!draft.model) throw new Error(`Step '${node.key}': choose a model.`)
  const version = {
    ...promptContent(draft, node.params.inputs),
    summary: 'Saved from the workflow editor.',
  }
  try {
    return (await createPromptVersion(NAMESPACE, slug, version)).n
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 404) throw error
  }
  return (await createNodePrompt(slug, name, version)).latest_version || 1
}
