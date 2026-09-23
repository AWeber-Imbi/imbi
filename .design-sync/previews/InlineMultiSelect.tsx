import { type ReactNode, useEffect, useRef } from 'react'

import { InlineMultiSelect } from 'imbi-ui'

const save = async () => {}

const PROJECT_TYPES = [
  { label: 'HTTP API', value: 'http-api' },
  { label: 'Queue Consumer', value: 'consumer' },
  { label: 'Scheduled Job', value: 'scheduled-job' },
  { label: 'Python Library', value: 'python-library' },
  { label: 'Frontend', value: 'frontend' },
]

const LANGUAGES = [
  { label: 'python', value: 'python' },
  { label: 'typescript', value: 'typescript' },
  { label: 'go', value: 'go' },
]

const SELECTED_TYPES = ['http-api', 'consumer']
const SELECTED_LANGUAGES = ['python', 'typescript']

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

// InlineMultiSelect keeps its popover state internally; click the display
// once on mount so the card shows the open checkbox list. Capture device
// only.
const PreviewOnlyAutoOpen = ({ children }: { children: ReactNode }) => {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>('[role="button"]')?.click()
  }, [])
  return <div ref={ref}>{children}</div>
}

export const Display = () => (
  <div className="w-96">
    <Row label="Project types">
      <InlineMultiSelect
        onCommit={save}
        options={PROJECT_TYPES}
        values={SELECTED_TYPES}
      />
    </Row>
    <Row label="Languages">
      <InlineMultiSelect
        onCommit={save}
        options={LANGUAGES}
        values={SELECTED_LANGUAGES}
      />
    </Row>
  </div>
)

export const Editing = () => (
  <div className="w-96">
    <Row label="Project types">
      <PreviewOnlyAutoOpen>
        <InlineMultiSelect
          onCommit={save}
          options={PROJECT_TYPES}
          values={SELECTED_TYPES}
        />
      </PreviewOnlyAutoOpen>
    </Row>
  </div>
)

export const EmptyReadOnlyPending = () => (
  <div className="w-96">
    <Row label="Project types">
      <InlineMultiSelect onCommit={save} options={PROJECT_TYPES} values={[]} />
    </Row>
    <Row label="Languages (read-only)">
      <InlineMultiSelect
        onCommit={save}
        options={LANGUAGES}
        readOnly
        values={SELECTED_LANGUAGES}
      />
    </Row>
    <Row label="Languages (saving)">
      <InlineMultiSelect
        onCommit={save}
        options={LANGUAGES}
        pending
        values={SELECTED_LANGUAGES}
      />
    </Row>
  </div>
)
