import { type ReactNode, useEffect, useRef } from 'react'

import { InlineArray } from 'imbi-ui'

const save = async () => {}

// Module-level lists: InlineArray re-syncs its draft when `values` changes
// identity while open.
const LANGUAGES = ['python', 'typescript']
const PORTS = [8000, 8080]
const ALIASES = ['imbi', 'imbi-api']

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

// InlineArray keeps its popover state internally; click the display once
// on mount so the card shows the open item editor. Capture device only.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="button"]')?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}

export const Display = () => (
  <div className="w-96">
    <Row label="Languages">
      <InlineArray onCommit={save} values={LANGUAGES} />
    </Row>
    <Row label="Ports">
      <InlineArray itemType="integer" onCommit={save} values={PORTS} />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-96">
    <Row label="Languages">
      <PreviewOnlyAutoOpen>
        <InlineArray onCommit={save} values={LANGUAGES} />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const EmptyReadOnlyPending = () => (
  <div className="w-96">
    <Row label="Languages">
      <InlineArray onCommit={save} placeholder="Add language…" values={[]} />
    </Row>
    <Row label="Aliases (read-only)">
      <InlineArray onCommit={save} readOnly values={ALIASES} />
    </Row>
    <Row label="Ports (saving)">
      <InlineArray itemType="integer" onCommit={save} pending values={PORTS} />
    </Row>
  </div>
)
