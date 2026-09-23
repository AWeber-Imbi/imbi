import { type ReactNode, useEffect, useRef } from 'react'

import { InlineSwitch } from 'imbi-ui'

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

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

export const Display = () => (
  <div className="w-80">
    <Row label="Public API">
      <InlineSwitch onCommit={save} value />
    </Row>
    <Row label="PagerDuty Paging">
      <InlineSwitch onCommit={save} value={false} />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-80">
    <Row label="Public API">
      <PreviewOnlyAutoOpen>
        <InlineSwitch onCommit={save} value />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const CustomDisplay = () => (
  <div className="w-80">
    <Row label="Public API">
      <InlineSwitch
        onCommit={save}
        renderDisplay={<span className="text-sm text-green-600">Enabled</span>}
        value
      />
    </Row>
  </div>
)

export const States = () => (
  <div className="w-80">
    <Row label="SOC 2 Scope">
      <InlineSwitch onCommit={save} value={null} />
    </Row>
    <Row label="Public API">
      <InlineSwitch onCommit={save} pending value />
    </Row>
    <Row label="Archived">
      <InlineSwitch onCommit={save} readOnly value={false} />
    </Row>
  </div>
)
