import { useState } from 'react'

import { DynamicFormFields } from 'imbi-ui'

// Extra blueprint fields on the "HTTP API" project type, as the API's
// OpenAPI schema describes them.
const SCHEMA = {
  properties: {
    framework: {
      description: 'Primary web framework',
      enum: ['FastAPI', 'Tornado', 'Flask', 'Django'],
      title: 'Framework',
      type: 'string',
    },
    health_check_path: {
      description: 'Path the load balancer polls',
      title: 'Health Check Path',
      type: 'string',
    },
    default_replicas: {
      maximum: 20,
      minimum: 1,
      title: 'Default Replicas',
      type: 'integer',
    },
    sla_target: {
      description: 'Monthly uptime target, percent',
      title: 'SLA Target',
      type: 'number',
    },
    runbook_url: { format: 'uri', title: 'Runbook URL', type: 'string' },
    public_api: {
      description: 'reachable from outside the VPC',
      title: 'Public API',
      type: 'boolean',
    },
  },
  required: ['framework', 'health_check_path'],
}

const FILLED = {
  default_replicas: 3,
  framework: 'FastAPI',
  health_check_path: '/status',
  public_api: true,
  runbook_url: 'https://wiki.example.com/runbooks/http-api',
  sla_target: 99.9,
}

function Form(props: {
  errors?: Record<string, string>
  initial: Record<string, unknown>
  isLoading?: boolean
}) {
  const [data, setData] = useState(props.initial)
  return (
    <div className="w-96 space-y-4">
      <DynamicFormFields
        data={data}
        errors={props.errors ?? {}}
        isLoading={props.isLoading}
        onChange={(key, value) => setData((d) => ({ ...d, [key]: value }))}
        schema={SCHEMA}
      />
    </div>
  )
}

export const Filled = () => <Form initial={FILLED} />

export const Empty = () => <Form initial={{}} />

export const WithErrors = () => (
  <Form
    errors={{
      framework: "must have required property 'framework'",
      runbook_url: 'must match format "uri"',
    }}
    initial={{ ...FILLED, framework: undefined, runbook_url: 'wiki/runbook' }}
  />
)

export const Loading = () => <Form initial={FILLED} isLoading />
