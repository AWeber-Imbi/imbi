import { useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import { Play } from 'lucide-react'

import { previewScript } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { FormField } from '@/components/ui/form-field'
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'

import { JsonBlock } from './JsonBlock'
import { hasTemplate, isRecord } from './schemaFields'
import type { ScriptPreviewRequest, WorkflowNode } from './types'

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
  // Follows the step's inputs until the user edits it.
  const [edited, setSample] = useState<null | string>(null)
  const sample =
    edited ?? JSON.stringify(sampleInputs(node.params.inputs), null, 2)
  const inputs = parseObject(sample)
  const run = useMutation({
    mutationFn: (body: ScriptPreviewRequest) => previewScript(orgSlug, body),
  })
  const body: ScriptPreviewRequest = {
    ...(node.params as Omit<ScriptPreviewRequest, 'inputs'>),
    inputs: inputs ?? {},
  }
  // A result shows only while the step still matches what was run.
  const stale =
    run.variables !== undefined &&
    JSON.stringify(run.variables) !== JSON.stringify(body)
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
        disabled={!inputs || run.isPending}
        onClick={() => run.mutate(body)}
        size="sm"
        type="button"
        variant="secondary"
      >
        <Play />
        {run.isPending ? 'Running…' : 'Run script'}
      </Button>
      {stale && (run.isPending || run.data || run.isError) && (
        <p className="text-tertiary text-xs">
          The step changed after you ran it. Run the script again to see a
          current result.
        </p>
      )}
      {!stale && run.isError && (
        <p className="text-danger text-xs" role="alert">
          {extractApiErrorDetail(run.error)}
        </p>
      )}
      {!stale && run.data?.error && (
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
      {!stale && run.data?.output && (
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
    return isRecord(value) ? value : null
  } catch {
    return null
  }
}

/** The node's inputs, with `null` for each value that holds a template. */
function sampleInputs(inputs: unknown): Record<string, unknown> {
  if (!isRecord(inputs)) return {}
  return Object.fromEntries(
    Object.entries(inputs).map(([name, value]) => [
      name,
      typeof value === 'string' && hasTemplate(value) ? null : value,
    ]),
  )
}
