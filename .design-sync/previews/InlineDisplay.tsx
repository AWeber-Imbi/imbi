import type { ReactNode } from 'react'

import { InlineDisplay } from 'imbi-ui'

const noop = () => {}

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

// InlineDisplay is the read-state shell every Inline* editor renders:
// value (or italic placeholder), a hover pencil, and a spinner while
// saving. `onClick` switches the parent editor into edit mode.
export const WithValue = () => (
  <div className="w-96">
    <Row label="Owner team">
      <InlineDisplay hasValue onClick={noop}>
        <span className="text-primary text-sm">Platform Engineering</span>
      </InlineDisplay>
    </Row>
    <Row label="SLO target">
      <InlineDisplay hasValue onClick={noop}>
        <span className="text-primary text-sm">99.9%</span>
      </InlineDisplay>
    </Row>
  </div>
)

export const Placeholder = () => (
  <div className="w-96">
    <Row label="Go-live date">
      <InlineDisplay hasValue={false} onClick={noop} />
    </Row>
    <Row label="Tier">
      <InlineDisplay hasValue={false} onClick={noop} placeholder="Select…" />
    </Row>
  </div>
)

export const PendingAndReadOnly = () => (
  <div className="w-96">
    <Row label="Tier (saving)">
      <InlineDisplay hasValue onClick={noop} pending>
        <span className="text-primary text-sm">Tier 2</span>
      </InlineDisplay>
    </Row>
    <Row label="Created (read-only)">
      <InlineDisplay hasValue onClick={noop} readOnly>
        <span className="text-primary text-sm">Mar 11, 2024</span>
      </InlineDisplay>
    </Row>
  </div>
)
