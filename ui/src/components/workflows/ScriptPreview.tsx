import { useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import { Play } from 'lucide-react'

import { previewScript } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'

import { JsonBlock } from './JsonBlock'
import type { ScriptPreviewRequest, WorkflowNode } from './types'

const TEMPLATE_MARKERS = ['{{', '{%']

/**
 * Run the node's script now with sample inputs (ADR 0027). The script
 * runs in the same sandbox, with the same limits, as in a run. Nothing
 * is saved, and references are not rendered.
 */
export function ScriptPreview({
  node,
  orgSlug,
}: {
  node: WorkflowNode
  orgSlug: string
}) {
  const [sample, setSample] = useState(() =>
    JSON.stringify(sampleInputs(node.params.inputs), null, 2),
  )
  const inputs = parseObject(sample)
  const run = useMutation({
    mutationFn: (body: ScriptPreviewRequest) => previewScript(orgSlug, body),
  })
  const id = `workflow-node-${node.id}-sample`
  return (
    <div className="border-tertiary flex flex-col gap-3 border-t pt-4">
      <FormField
        description="The values the script gets here. References are not rendered: write a sample value for each."
        error={inputs ? undefined : 'Write a JSON object.'}
        htmlFor={id}
        label="Sample inputs"
        touched
      >
        <Textarea
          className="font-mono text-xs"
          id={id}
          onChange={(e) => setSample(e.target.value)}
          rows={4}
          spellCheck={false}
          value={sample}
        />
      </FormField>
      <Button
        className="self-start"
        disabled={!inputs || run.isPending}
        onClick={() =>
          run.mutate({
            ...(node.params as Omit<ScriptPreviewRequest, 'inputs'>),
            inputs: inputs ?? {},
          })
        }
        size="sm"
        type="button"
        variant="secondary"
      >
        <Play />
        {run.isPending ? 'Running…' : 'Run script'}
      </Button>
      {run.isError && (
        <p className="text-danger text-xs" role="alert">
          {extractApiErrorDetail(run.error)}
        </p>
      )}
      {run.data?.error && (
        <dl className="grid grid-cols-[90px_1fr] gap-x-3 gap-y-1.5 text-sm">
          <dt className="text-tertiary">Error</dt>
          <dd className="text-danger font-mono text-xs">{run.data.error}</dd>
          {run.data.message && (
            <>
              <dt className="text-tertiary">Message</dt>
              <dd className="font-mono text-xs break-words">
                {run.data.message}
              </dd>
            </>
          )}
        </dl>
      )}
      {run.data?.output && (
        <>
          {run.data.output.branch && (
            <dl className="grid grid-cols-[90px_1fr] gap-x-3 text-sm">
              <dt className="text-tertiary">Branch</dt>
              <dd className="font-medium">{run.data.output.branch}</dd>
            </dl>
          )}
          <JsonBlock label="Result" value={run.data.output.result} />
          {run.data.output.stdout && (
            <JsonBlock label="Printed" value={run.data.output.stdout} />
          )}
        </>
      )}
    </div>
  )
}

function parseObject(text: string): null | Record<string, unknown> {
  if (!text.trim()) return {}
  try {
    const value: unknown = JSON.parse(text)
    return value && typeof value === 'object' && !Array.isArray(value)
      ? (value as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

/** The node's inputs, with `null` for each value that holds a template. */
function sampleInputs(inputs: unknown): Record<string, unknown> {
  if (!inputs || typeof inputs !== 'object' || Array.isArray(inputs)) return {}
  return Object.fromEntries(
    Object.entries(inputs).map(([name, value]) => [
      name,
      typeof value === 'string' &&
      TEMPLATE_MARKERS.some((m) => value.includes(m))
        ? null
        : value,
    ]),
  )
}
