import { useState } from 'react'

import { MarkdownPreview } from '@/components/ui/markdown-editor/MarkdownPreview'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'

import { AGENT_PROMPT_VARIABLES, wordCount } from './agentDraft'

type Mode = 'preview' | 'split' | 'write'

// The prompt CMS renders Jinja, so the tokens use that syntax.
const VARIABLES = Object.entries(AGENT_PROMPT_VARIABLES).map(
  ([name, spec]) => ({ note: spec.description, token: `{{ ${name} }}` }),
)

interface SystemPromptTabProps {
  onChange: (system: string) => void
  value: string
}

export function SystemPromptTab({ onChange, value }: SystemPromptTabProps) {
  const [mode, setMode] = useState<Mode>('split')
  const words = wordCount(value)
  // About four characters for each token in English text.
  const tokens = Math.ceil(value.length / 4)

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <SegmentedControl
          ariaLabel="Editor layout"
          onValueChange={(v) => setMode(v as Mode)}
          value={mode}
        >
          <SegmentedControlItem value="write">Write</SegmentedControlItem>
          <SegmentedControlItem value="split">Split</SegmentedControlItem>
          <SegmentedControlItem value="preview">Preview</SegmentedControlItem>
        </SegmentedControl>
        <span className="text-xs text-tertiary">Markdown</span>
        <span className="ml-auto font-mono text-xs text-tertiary tabular-nums">
          {words.toLocaleString()} words · ~{tokens.toLocaleString()} tokens
        </span>
      </div>
      <div
        className={cn(
          'grid min-h-155 gap-4',
          mode === 'split' ? 'grid-cols-2' : 'grid-cols-1',
        )}
      >
        {mode !== 'preview' && (
          <Textarea
            aria-label="System prompt"
            className="h-full font-mono leading-relaxed"
            onChange={(e) => onChange(e.target.value)}
            placeholder="You are…"
            rows={28}
            value={value}
          />
        )}
        {mode !== 'write' && (
          <div className="max-h-180 min-h-155 overflow-y-auto rounded-md border border-border bg-card px-6 py-5">
            <MarkdownPreview value={value} />
          </div>
        )}
      </div>
      <div className="rounded-lg border border-border bg-card p-6">
        <div className="mb-1 text-overline text-tertiary uppercase">
          Available variables
        </div>
        <p className="mb-3 text-xs text-tertiary">
          Imbi fills in these values when a runner starts a task.
        </p>
        <div className="flex flex-col gap-2">
          {VARIABLES.map((v) => (
            <div className="flex items-baseline gap-4" key={v.token}>
              <span className="w-50 font-mono text-xs text-action">
                {v.token}
              </span>
              <span className="text-xs text-secondary">{v.note}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
