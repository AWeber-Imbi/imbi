import { type ReactNode, useEffect, useRef } from 'react'

import { InlineSelect } from 'imbi-ui'

const save = async () => {}

const TIERS = [
  { label: 'Tier 1', value: '1' },
  { label: 'Tier 2', value: '2' },
  { label: 'Tier 3', value: '3' },
]

const TEAMS = [
  { label: 'Platform Engineering', value: 'platform' },
  { label: 'Data Services', value: 'data' },
  { label: 'Messaging', value: 'messaging' },
  { label: 'Site Reliability', value: 'sre' },
]

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

// InlineSelect keeps its editing state internally; click the display once
// on mount so the card shows the open option list. Capture device only.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="button"]')?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}

export const Display = () => (
  <div className="w-96">
    <Row label="Owner team">
      <InlineSelect onCommit={save} options={TEAMS} value="platform" />
    </Row>
    <Row label="Tier">
      <InlineSelect onCommit={save} options={TIERS} value="2" />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-96">
    <Row label="Tier">
      <PreviewOnlyAutoOpen>
        <InlineSelect onCommit={save} options={TIERS} value="2" />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const CustomDisplay = () => (
  <div className="w-96">
    <Row label="Tier">
      <InlineSelect
        onCommit={save}
        options={TIERS}
        renderDisplay={
          <span className="text-sm font-medium text-red-600">
            Tier 1 · critical
          </span>
        }
        value="1"
      />
    </Row>
  </div>
)

export const EmptyReadOnlyPending = () => (
  <div className="w-96">
    <Row label="Tier">
      <InlineSelect onCommit={save} options={TIERS} value={null} />
    </Row>
    <Row label="Owner team (read-only)">
      <InlineSelect onCommit={save} options={TEAMS} readOnly value="data" />
    </Row>
    <Row label="Owner team (saving)">
      <InlineSelect onCommit={save} options={TEAMS} pending value="sre" />
    </Row>
  </div>
)
