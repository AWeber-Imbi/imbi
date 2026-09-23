import { DynamicDetailFields } from 'imbi-ui'

// Extra blueprint fields on the "HTTP API" project type, as the API's
// OpenAPI schema describes them.
const SCHEMA = {
  properties: {
    framework: {
      enum: ['FastAPI', 'Tornado', 'Flask', 'Django'],
      title: 'Framework',
      type: 'string',
    },
    health_check_path: { title: 'Health Check Path', type: 'string' },
    default_replicas: { title: 'Default Replicas', type: 'integer' },
    sla_target: { title: 'SLA Target', type: 'number' },
    launch_date: { format: 'date', title: 'Launch Date', type: 'string' },
    public_api: { title: 'Public API', type: 'boolean' },
    // No `title`: the label falls back to title-cased key.
    pager_rotation: { type: 'string' },
  },
}

// Same layout the admin detail cards use: a two-column grid of
// label / value pairs.
export const Default = () => (
  <div className="grid w-full max-w-xl grid-cols-2 gap-6">
    <DynamicDetailFields
      data={{
        default_replicas: 3,
        framework: 'FastAPI',
        health_check_path: '/status',
        launch_date: '2024-03-18',
        pager_rotation: 'platform-primary',
        public_api: true,
        sla_target: 99.9,
      }}
      schema={SCHEMA}
    />
  </div>
)

// Empty, null, and missing values are skipped; `false` shows as "No".
export const Partial = () => (
  <div className="grid w-full max-w-xl grid-cols-2 gap-6">
    <div>
      <div className="text-secondary text-sm">Slug</div>
      <div className="text-primary mt-1">
        <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
          staging
        </code>
      </div>
    </div>
    <DynamicDetailFields
      data={{
        framework: 'Tornado',
        health_check_path: '',
        public_api: false,
        sla_target: null,
      }}
      schema={SCHEMA}
    />
  </div>
)
