import { type ReactNode, useEffect, useRef } from 'react'

import { InlineText } from 'imbi-ui'

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
  <div className="w-96">
    <Row label="Slug">
      <InlineText
        onCommit={save}
        renderValue={(v) => (
          <span className="text-primary font-mono text-sm">{v}</span>
        )}
        value="imbi-api"
      />
    </Row>
    <Row label="Repository URL">
      <InlineText
        onCommit={save}
        renderValue={(v) => <span className="text-primary text-sm">{v}</span>}
        value="https://github.com/aweber/imbi-api"
      />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-96">
    <Row label="Slug">
      <PreviewOnlyAutoOpen>
        <InlineText
          inputClassName="w-48 font-mono text-sm"
          onCommit={save}
          value="imbi-api"
        />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const Empty = () => (
  <div className="w-96">
    <Row label="Repository URL">
      <InlineText onCommit={save} placeholder="Add a URL…" value={null} />
    </Row>
  </div>
)

export const Pending = () => (
  <div className="w-96">
    <Row label="Slug">
      <InlineText
        onCommit={save}
        pending
        renderValue={(v) => (
          <span className="text-primary font-mono text-sm">{v}</span>
        )}
        value="imbi-api"
      />
    </Row>
  </div>
)

export const ReadOnly = () => (
  <div className="w-96">
    <Row label="Project ID">
      <InlineText
        onCommit={save}
        readOnly
        renderValue={(v) => (
          <span className="text-primary font-mono text-sm">{v}</span>
        )}
        value="prj_01HZX4K7Q2"
      />
    </Row>
  </div>
)
