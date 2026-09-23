import { useRef, useState } from 'react'

import { MarkdownToolbar, useMarkdownFormatting } from 'imbi-ui'

// Ported from the `Toolbar` story: the toolbar on its own, wired to a
// caller's textarea with `useMarkdownFormatting`.
function Wired(props: { disabled?: boolean; initial: string }) {
  const [value, setValue] = useState(props.initial)
  const ref = useRef<HTMLTextAreaElement>(null)
  const { format, onKeyDown } = useMarkdownFormatting(ref, setValue)
  return (
    <div className="border-input w-full max-w-xl rounded-md border">
      <MarkdownToolbar
        className="border-input border-b px-2 py-1"
        disabled={props.disabled}
        onFormat={format}
      />
      <textarea
        aria-label="Document body"
        className="bg-background block min-h-40 w-full resize-y px-3 py-2 font-mono text-xs outline-none"
        disabled={props.disabled}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={onKeyDown}
        ref={ref}
        value={value}
      />
    </div>
  )
}

export const Toolbar = () => (
  <Wired
    initial={
      '## Deploy checklist\n\nSelect some text and format it.\n\n- Run migrations\n- Promote to production'
    }
  />
)

export const Disabled = () => (
  <Wired disabled initial="Locked while the document is being published." />
)

export const Standalone = () => (
  <div className="w-80">
    <MarkdownToolbar onFormat={() => {}} />
  </div>
)
