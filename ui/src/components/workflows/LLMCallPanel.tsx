import { useState } from 'react'

import { useMutation, useQuery } from '@tanstack/react-query'
import { Play } from 'lucide-react'

import { listAIModels, runPrompt } from '@/api/endpoints'
import { formatMoney } from '@/components/agents/agentDraft'
import { usePromptResolution } from '@/components/agents/agentQueries'
import { AIModelSelect } from '@/components/prompts/AIModelSelect'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type { PromptRunRequest } from '@/types'

import { InputsField } from './InputsField'
import { JsonBlock } from './JsonBlock'
import {
  draftFromVersion,
  EMPTY_PROMPT,
  ensurePrompt,
  NAMESPACE,
  pinnedRef,
  promptContent,
  promptSlug,
  type StepPrompt,
} from './llmCallPrompt'
import type { OutputField } from './outputFields'
import { OutputFieldsField } from './OutputFieldsField'
import type { ReferenceGroup } from './references'
import { isRecord } from './schemaFields'
import { parseSample, sampleInputs } from './ScriptPreview'
import type { WorkflowNode } from './types'

/**
 * The params of an LLM Call step. The prompt, the model, and its
 * params are stored in the Prompt CMS when the workflow is saved; the
 * inputs and the output fields are step params.
 */
export function LLMCallPanel({
  node,
  onChange,
  onPromptChange,
  orgSlug,
  prompt,
  references,
  workflowName,
  workflowSlug,
}: {
  node: WorkflowNode
  onChange: (params: Record<string, unknown>) => void
  onPromptChange: (prompt: StepPrompt) => void
  orgSlug: string
  /** The edited prompt, or undefined to show the pinned version. */
  prompt: StepPrompt | undefined
  references: ReferenceGroup[]
  workflowName: string
  /** Undefined until the workflow is saved for the first time. */
  workflowSlug: string | undefined
}) {
  const ref = pinnedRef(node)
  const loaded = usePromptResolution(prompt ? null : ref)
  const models = useQuery({
    queryFn: ({ signal }) => listAIModels(signal),
    queryKey: queryKeys.aiModels(),
  })
  if (!prompt && ref && loaded.isLoading) {
    return <p className="text-tertiary text-sm">Loading the prompt…</p>
  }
  // An edit of an empty draft would save a version without the
  // pinned content, so the fields wait for the pinned version.
  if (!prompt && ref && !loaded.data) {
    return (
      <div className="flex flex-col items-start gap-2">
        <p className="text-danger text-xs" role="alert">
          Failed to load the prompt {ref}.
        </p>
        <Button
          disabled={loaded.isFetching}
          onClick={() => void loaded.refetch()}
          size="sm"
          type="button"
          variant="outline"
        >
          Retry
        </Button>
      </div>
    )
  }
  const current =
    prompt ?? (loaded.data ? draftFromVersion(loaded.data) : EMPTY_PROMPT)
  const set = (patch: Partial<StepPrompt>) =>
    onPromptChange({ ...current, ...patch })
  const setParam = (name: string, value: unknown) =>
    onChange({ ...node.params, [name]: value })
  const outputFields = Array.isArray(node.params.output_fields)
    ? (node.params.output_fields as OutputField[])
    : []
  const structured = models.data?.some(
    (m) => m.slug === current.model && m.supports_structured_output,
  )
  // Only a loaded catalog can tell that the model has no structured output.
  const unsupported = models.isSuccess && !structured
  const id = `workflow-node-${node.id}`
  const slug = promptSlug(orgSlug, workflowSlug ?? '', node.key)
  return (
    <>
      <FormField label="Model" required>
        <AIModelSelect
          onChange={(model) => set({ model })}
          value={current.model}
        />
      </FormField>
      <FormField
        description="Jinja2. Use each input as {{ name }}."
        htmlFor={`${id}-system`}
        label="System prompt"
      >
        <Textarea
          className="font-mono text-xs"
          id={`${id}-system`}
          onChange={(e) => set({ system: e.target.value })}
          rows={4}
          value={current.system}
        />
      </FormField>
      <FormField htmlFor={`${id}-user`} label="User message" required>
        <Textarea
          className="font-mono text-xs"
          id={`${id}-user`}
          onChange={(e) => set({ user: e.target.value })}
          rows={6}
          value={current.user}
        />
      </FormField>
      <div className="grid grid-cols-2 gap-3">
        <NumberField
          id={`${id}-max-tokens`}
          label="Max tokens"
          onChange={(max_tokens) => set({ max_tokens })}
          value={current.max_tokens}
        />
        <NumberField
          id={`${id}-temperature`}
          label="Temperature"
          onChange={(temperature) => set({ temperature })}
          value={current.temperature}
        />
      </div>
      <FormField
        description="The variables of the prompt. A value can be a reference, such as {{ fetch.result }}."
        htmlFor={`${id}-inputs`}
        label="Inputs"
      >
        <InputsField
          id={`${id}-inputs`}
          keywords="jinja"
          label="Inputs"
          onChange={(inputs) => setParam('inputs', inputs)}
          references={references}
          value={isRecord(node.params.inputs) ? node.params.inputs : {}}
        />
      </FormField>
      <FormField
        description={
          !unsupported || outputFields.length
            ? 'The structured answer. Later steps use {{ <key>.result.<field> }}.'
            : 'The model does not support structured output. Later steps use {{ <key>.text }}.'
        }
        htmlFor={`${id}-output-fields`}
        label="Output fields"
      >
        {/* A field that the model cannot fill can still be removed. */}
        <fieldset disabled={!structured && !outputFields.length}>
          <OutputFieldsField
            id={`${id}-output-fields`}
            label="Output fields"
            onChange={(fields) => setParam('output_fields', fields)}
            value={outputFields}
          />
        </fieldset>
        {unsupported && outputFields.length > 0 && (
          <p className="text-danger mt-1 text-xs">
            The model does not support structured output. Remove the fields or
            choose another model.
          </p>
        )}
      </FormField>
      <LLMCallPreview
        exists={node.params.prompt_ref === `${NAMESPACE}/${slug}`}
        inputs={node.params.inputs}
        name={`${workflowName} / ${node.title}`}
        orgSlug={orgSlug}
        outputFields={outputFields}
        saved={workflowSlug !== undefined}
        slug={slug}
        version={promptContent(current, node.params.inputs)}
      />
    </>
  )
}

/** Run the draft prompt now with sample values. Nothing is saved. */
function LLMCallPreview({
  exists,
  inputs,
  name,
  orgSlug,
  outputFields,
  saved,
  slug,
  version,
}: {
  /** The node's prompt is in the CMS already. */
  exists: boolean
  inputs: unknown
  name: string
  orgSlug: string
  outputFields: OutputField[]
  /** The workflow exists, so its prompts can be created. */
  saved: boolean
  slug: string
  version: NonNullable<PromptRunRequest['draft']>['version']
}) {
  // Follows the step's inputs until the user edits it.
  const [edited, setSample] = useState<null | string>(null)
  const sample = edited ?? JSON.stringify(sampleInputs(inputs), null, 2)
  const variables = parseSample(sample)
  const body: PromptRunRequest = {
    draft: { namespace: NAMESPACE, slug, version },
    // The API fills the defaults of a field.
    output_fields: outputFields as PromptRunRequest['output_fields'],
    variables: variables ?? {},
  }
  const run = useMutation({
    mutationFn: async (body: PromptRunRequest) => {
      // A draft runs as a version of an existing prompt.
      if (!exists) await ensurePrompt(slug, name, version)
      return runPrompt(orgSlug, body)
    },
  })
  const stale =
    run.variables !== undefined &&
    JSON.stringify(run.variables) !== JSON.stringify(body)
  const id = `${slug}-sample`
  return (
    <div className="border-tertiary flex flex-col gap-3 border-t pt-4">
      <FormField
        description="The values of the inputs here. References are not rendered: write a sample value for each."
        error={variables ? undefined : 'Write a JSON object.'}
        htmlFor={id}
        label="Sample inputs"
        touched
      >
        <Textarea
          className="font-mono text-xs"
          disabled={run.isPending}
          id={id}
          onChange={(e) => {
            setSample(e.target.value)
            run.reset()
          }}
          rows={4}
          spellCheck={false}
          value={sample}
        />
      </FormField>
      <Button
        className="self-start"
        disabled={!saved || !variables || !version.model || run.isPending}
        onClick={() => run.mutate(body)}
        size="sm"
        type="button"
        variant="secondary"
      >
        <Play />
        {run.isPending ? 'Running…' : 'Run prompt'}
      </Button>
      {!saved && (
        <p className="text-tertiary text-xs">Save the workflow first.</p>
      )}
      {stale && (run.isPending || run.data || run.isError) && (
        <p className="text-tertiary text-xs">
          The step changed after you ran it. Run the prompt again to see a
          current result.
        </p>
      )}
      {!stale && run.isError && (
        <p className="text-danger text-xs" role="alert">
          {readable(extractApiErrorDetail(run.error))}
        </p>
      )}
      {!stale && run.data && (
        <>
          <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1.5 text-sm">
            <dt className="text-tertiary">Model</dt>
            <dd className="font-mono text-xs">{run.data.model_id}</dd>
            <dt className="text-tertiary">Tokens</dt>
            <dd className="font-mono text-xs">
              {String(run.data.usage.input_tokens ?? '—')} in ·{' '}
              {String(run.data.usage.output_tokens ?? '—')} out
            </dd>
            <dt className="text-tertiary">Cost</dt>
            <dd className="font-mono text-xs">
              {run.data.cost_usd == null
                ? '—'
                : formatMoney(run.data.cost_usd, 4)}
            </dd>
          </dl>
          {run.data.result ? (
            <JsonBlock label="Result" value={run.data.result} />
          ) : (
            <JsonBlock label="Text" value={run.data.text ?? ''} />
          )}
        </>
      )}
    </div>
  )
}

/** An optional number; an empty field is null. */
function NumberField({
  id,
  label,
  onChange,
  value,
}: {
  id: string
  label: string
  onChange: (value: null | number) => void
  value: null | number
}) {
  return (
    <FormField htmlFor={id} label={label}>
      <Input
        id={id}
        onChange={(e) =>
          onChange(e.target.value === '' ? null : Number(e.target.value))
        }
        step="any"
        type="number"
        value={value ?? ''}
      />
    </FormField>
  )
}

/** An error code such as `model_answer_invalid` as words. */
function readable(detail: string): string {
  if (!/^[a-z_]+$/.test(detail)) return detail
  const words = detail.replace(/_/g, ' ')
  return words.charAt(0).toUpperCase() + words.slice(1)
}
