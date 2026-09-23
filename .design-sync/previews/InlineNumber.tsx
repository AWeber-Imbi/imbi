import { type ReactNode, useEffect, useRef } from 'react'

import { InlineNumber } from 'imbi-ui'

const save = async () => {}

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

// InlineNumber keeps its editing state internally; click the display once
// on mount so the card shows the number input. Capture device only.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="button"]')?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}

export const Display = () => (
  <div className="w-96">
    <Row label="SLO target">
      <InlineNumber
        max={100}
        min={0}
        onCommit={save}
        renderDisplay={<span className="text-primary text-sm">99.9%</span>}
        step={0.1}
        value={99.9}
      />
    </Row>
    <Row label="Replicas">
      <InlineNumber integer min={1} onCommit={save} value={3} />
    </Row>
    <Row label="Port">
      <InlineNumber integer max={65535} min={1} onCommit={save} value={8000} />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-96">
    <Row label="Replicas">
      <PreviewOnlyAutoOpen>
        <InlineNumber integer min={1} onCommit={save} value={3} />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const Empty = () => (
  <div className="w-96">
    <Row label="SLO target">
      <InlineNumber max={100} min={0} onCommit={save} value={null} />
    </Row>
    <Row label="Error budget (min)">
      <InlineNumber
        integer
        onCommit={save}
        placeholder="Set budget…"
        value={null}
      />
    </Row>
  </div>
)

export const ReadOnlyAndPending = () => (
  <div className="w-96">
    <Row label="Replicas (read-only)">
      <InlineNumber integer onCommit={save} readOnly value={3} />
    </Row>
    <Row label="Port (saving)">
      <InlineNumber integer onCommit={save} pending value={8080} />
    </Row>
  </div>
)
