import { type ReactNode, useEffect, useRef } from 'react'

import { InlineDate } from 'imbi-ui'

const save = async () => {}

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

// InlineDate keeps its popover state internally; click the display once on
// mount so the card shows the open calendar. Capture device only.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="button"]')?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}


// The display is formatted in the viewer's time zone, so it always matches
// the day the calendar selects.
const REVIEWED_AT = '2026-09-14T15:30:00Z'
export const Display = () => (
  <div className="w-96">
    <Row label="Go-live date">
      <InlineDate onCommit={save} value="2026-07-29" />
    </Row>
    <Row label="Last reviewed">
      <InlineDate
        mode="date-time"
        onCommit={save}
        renderDisplay={
          <span className="text-primary text-sm">
            {new Date(REVIEWED_AT).toLocaleDateString('en-US', {
              day: 'numeric',
              month: 'short',
              year: 'numeric',
            })}
          </span>
        }
        value={REVIEWED_AT}
      />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-96">
    <Row label="Go-live date">
      <PreviewOnlyAutoOpen>
        <InlineDate onCommit={save} value="2026-07-29" />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const EmptyReadOnlyPending = () => (
  <div className="w-96">
    <Row label="Go-live date">
      <InlineDate onCommit={save} placeholder="Set date…" value={null} />
    </Row>
    <Row label="Created (read-only)">
      <InlineDate onCommit={save} readOnly value="2024-03-11" />
    </Row>
    <Row label="Sunset date (saving)">
      <InlineDate onCommit={save} pending value="2027-01-31" />
    </Row>
  </div>
)
