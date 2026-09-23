import { type ReactNode, useEffect, useRef } from 'react'

import { InlineTextarea } from 'imbi-ui'

// Stand-in for the API PATCH the project page sends on commit.
const save = async () => {}

// Preview-only capture helper: click the display once on mount so the
// card shows the editing state. Not an app pattern.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="button"]')?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}

const DESCRIPTION =
  'Core REST API for Imbi. Serves projects, environments, and ops log ' +
  'entries to the UI, MCP server, and Slack bot.'

export const Display = () => (
  <div className="text-secondary max-w-xl w-full">
    <InlineTextarea
      onCommit={save}
      placeholder="Add a description…"
      rows={2}
      value={DESCRIPTION}
    />
  </div>
)

export const Editing = () => (
  <div className="text-secondary max-w-xl w-full">
    <PreviewOnlyAutoOpen>
      <InlineTextarea
        onCommit={save}
        placeholder="Add a description…"
        rows={3}
        value={DESCRIPTION}
      />
    </PreviewOnlyAutoOpen>
  </div>
)

export const Empty = () => (
  <div className="text-secondary max-w-xl w-full">
    <InlineTextarea
      onCommit={save}
      placeholder="Add a description…"
      rows={2}
      value={null}
    />
  </div>
)

export const ReadOnly = () => (
  <div className="text-secondary max-w-xl w-full">
    <InlineTextarea
      onCommit={save}
      readOnly
      value="Archived: replaced by imbi-gateway in 2.30."
    />
  </div>
)
