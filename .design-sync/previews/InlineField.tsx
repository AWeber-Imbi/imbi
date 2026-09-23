import type { ReactNode } from 'react'

import { Card, CardContent, CardHeader, CardTitle, InlineField } from 'imbi-ui'

const save = async () => {}

// InlineField picks the editor from a project-schema property `def`:
// enum -> InlineSelect, array -> InlineArray / InlineMultiSelect (item
// enum), boolean -> InlineSwitch, date/date-time -> InlineDate,
// integer/number -> InlineNumber, anything else -> InlineText.
const DEFS = {
  description: { title: 'Description', type: 'string' },
  go_live: { format: 'date', title: 'Go-live date', type: 'string' },
  languages: {
    items: { enum: ['python', 'typescript', 'go'], type: 'string' },
    title: 'Languages',
    type: 'array',
  },
  pagerduty: { title: 'PagerDuty enabled', type: 'boolean' },
  slo: { maximum: 100, minimum: 0, title: 'SLO target', type: 'number' },
  tier: { enum: ['Tier 1', 'Tier 2', 'Tier 3'], title: 'Tier', type: 'string' },
}

const LANGUAGES = ['python', 'typescript']

const Row = ({ children, label }: { children: ReactNode; label: string }) => (
  <div className="border-tertiary flex items-center justify-between border-b py-1.5 last:border-0">
    <span className="text-tertiary text-sm">{label}</span>
    {children}
  </div>
)

const text = (v: string) => <span className="text-primary text-sm">{v}</span>

export const AttributeGrid = () => (
  <Card className="w-96">
    <CardHeader>
      <CardTitle>Attributes</CardTitle>
    </CardHeader>
    <CardContent>
      <Row label="Description">
        <InlineField
          def={DEFS.description}
          display={text('Imbi REST API')}
          onCommit={save}
          pending={false}
          raw="Imbi REST API"
        />
      </Row>
      <Row label="Go-live date">
        <InlineField
          def={DEFS.go_live}
          display={text('Jul 29, 2026')}
          onCommit={save}
          pending={false}
          raw="2026-07-29"
        />
      </Row>
      <Row label="Languages">
        <InlineField
          def={DEFS.languages}
          display={null}
          onCommit={save}
          pending={false}
          raw={LANGUAGES}
        />
      </Row>
      <Row label="PagerDuty enabled">
        <InlineField
          def={DEFS.pagerduty}
          display={text('Yes')}
          onCommit={save}
          pending={false}
          raw
        />
      </Row>
      <Row label="SLO target">
        <InlineField
          def={DEFS.slo}
          display={text('99.9%')}
          onCommit={save}
          pending={false}
          raw={99.9}
        />
      </Row>
      <Row label="Tier">
        <InlineField
          def={DEFS.tier}
          display={text('Tier 2')}
          onCommit={save}
          pending={false}
          raw="Tier 2"
        />
      </Row>
    </CardContent>
  </Card>
)

export const Unset = () => (
  <Card className="w-96">
    <CardHeader>
      <CardTitle>Attributes</CardTitle>
    </CardHeader>
    <CardContent>
      <Row label="Go-live date">
        <InlineField
          def={DEFS.go_live}
          display={null}
          onCommit={save}
          pending={false}
          raw={null}
        />
      </Row>
      <Row label="Languages">
        <InlineField
          def={DEFS.languages}
          display={null}
          onCommit={save}
          pending={false}
          raw={null}
        />
      </Row>
      <Row label="SLO target">
        <InlineField
          def={DEFS.slo}
          display={null}
          onCommit={save}
          pending={false}
          raw={null}
        />
      </Row>
      <Row label="Tier (saving)">
        <InlineField
          def={DEFS.tier}
          display={text('Tier 1')}
          onCommit={save}
          pending
          raw="Tier 1"
        />
      </Row>
    </CardContent>
  </Card>
)
