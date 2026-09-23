import { AttributeValue } from 'imbi-ui'

// Dates are offsets from now, so the card reads the same in capture
// (frozen clock) and in the live product.
const ago = (seconds: number) =>
  new Date(Date.now() - seconds * 1000).toISOString()

// Threshold maps (color-range,
// color-age) are evaluated in key order; the first match wins.
const OVERLINE = 'text-tertiary mb-1.5 text-overline font-semibold uppercase'

const LIFECYCLE = {
  enum: ['active', 'in_progress', 'deprecated'],
  title: 'Lifecycle',
  type: 'string',
  'x-display': { format: 'humanize' },
  'x-ui': {
    'color-map': { active: 'green', deprecated: 'red', in_progress: 'amber' },
  },
}

const COVERAGE = {
  maximum: 100,
  minimum: 0,
  title: 'Test Coverage',
  type: 'number',
  'x-ui': { 'color-range': { '<60': 'red', '<80': 'amber', '>=80': 'green' } },
}

const LAST_AUDIT = {
  format: 'date-time',
  title: 'Last Security Audit',
  type: 'string',
  'x-ui': { 'color-age': { '>90d': 'red', '>30d': 'amber', '<=30d': 'green' } },
}

const Field = ({ children, label }: { children: React.ReactNode; label: string }) => (
  <div className="min-w-0">
    <div className={OVERLINE}>{label}</div>
    {children}
  </div>
)

export const ColorMap = () => (
  <div className="flex flex-col gap-2">
    <AttributeValue def={LIFECYCLE} rawValue="active" />
    <AttributeValue def={LIFECYCLE} rawValue="in_progress" />
    <AttributeValue def={LIFECYCLE} rawValue="deprecated" />
  </div>
)

export const NumericRange = () => (
  <div className="flex flex-col gap-2">
    <AttributeValue def={COVERAGE} rawValue={92.4} />
    <AttributeValue def={COVERAGE} rawValue={71} />
    <AttributeValue def={COVERAGE} rawValue={48.5} />
  </div>
)

export const DateAge = () => (
  <div className="flex flex-col gap-2">
    <AttributeValue def={LAST_AUDIT} rawValue={ago(1116000)} />
    <AttributeValue def={LAST_AUDIT} rawValue={ago(4849200)} />
    <AttributeValue def={LAST_AUDIT} rawValue={ago(16313400)} />
  </div>
)

export const AttributeGrid = () => (
  <div
    className="grid w-full max-w-xl gap-4"
    style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}
  >
    <Field label="Lifecycle">
      <AttributeValue def={LIFECYCLE} rawValue="active" />
    </Field>
    <Field label="Replicas">
      <AttributeValue def={{ title: 'Replicas', type: 'integer' }} rawValue={12000} />
    </Field>
    <Field label="Public">
      <AttributeValue def={{ title: 'Public', type: 'boolean' }} rawValue="true" />
    </Field>
    <Field label="Runtime">
      <AttributeValue def={{ title: 'Runtime', type: 'string' }} rawValue="Python 3.14" />
    </Field>
    <Field label="On-call Rotation">
      <AttributeValue
        def={{ title: 'On-call Rotation', type: 'string' }}
        fallback={<span className="text-tertiary">&mdash;</span>}
        rawValue={null}
      />
    </Field>
  </div>
)
