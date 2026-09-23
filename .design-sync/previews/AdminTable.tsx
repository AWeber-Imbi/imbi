import { AdminTable, type AdminTableColumn } from 'imbi-ui'
import { Layers } from 'lucide-react'

interface ProjectType {
  description: string
  name: string
  projects: number
  slug: string
  updated: string
}

const projectTypes: ProjectType[] = [
  {
    description: 'Synchronous HTTP services',
    name: 'HTTP API',
    projects: 42,
    slug: 'http-api',
    updated: '2 days ago',
  },
  {
    description: 'RabbitMQ and Kafka consumers',
    name: 'Queue Consumer',
    projects: 18,
    slug: 'consumer',
    updated: '1 week ago',
  },
  {
    description: 'Cron-driven batch work',
    name: 'Scheduled Job',
    projects: 7,
    slug: 'scheduled-job',
    updated: '3 weeks ago',
  },
  {
    description: 'Shared Python packages on PyPI',
    name: 'Python Library',
    projects: 0,
    slug: 'python-library',
    updated: '2 months ago',
  },
]

const columns: AdminTableColumn<ProjectType>[] = [
  {
    cellAlign: 'left',
    header: 'Project Type',
    headerAlign: 'left',
    key: 'name',
    render: (pt) => (
      <div className="flex items-center gap-3">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-purple-50 dark:bg-purple-900/30">
          <Layers className="size-4 text-purple-600 dark:text-purple-400" />
        </div>
        <div>
          <div className="text-primary">{pt.name}</div>
          <div className="text-tertiary text-sm">{pt.description}</div>
        </div>
      </div>
    ),
  },
  {
    cellAlign: 'center',
    header: 'Slug',
    headerAlign: 'center',
    key: 'slug',
    render: (pt) => (
      <code className="bg-secondary text-primary rounded px-2 py-1">
        {pt.slug}
      </code>
    ),
  },
  {
    cellAlign: 'right',
    header: 'Projects',
    headerAlign: 'right',
    key: 'projects',
    render: (pt) => (
      <span className={pt.projects === 0 ? 'text-tertiary' : 'text-secondary'}>
        {pt.projects}
      </span>
    ),
  },
  {
    cellAlign: 'center',
    header: 'Last Updated',
    headerAlign: 'center',
    key: 'updated',
    render: (pt) => pt.updated,
  },
]

const canDelete = (pt: ProjectType) =>
  pt.projects === 0
    ? { allowed: true }
    : { allowed: false, blockedBy: [{ count: pt.projects, label: 'project' }] }

export const ProjectTypes = () => (
  <div className="w-full max-w-4xl">
    <AdminTable
      canDelete={canDelete}
      columns={columns}
      getDeleteLabel={(pt) => pt.name}
      getRowHref={(pt) => `/admin/project-types/${pt.slug}`}
      getRowKey={(pt) => pt.slug}
      onDelete={() => {}}
      rows={projectTypes}
    />
  </div>
)

export const Loading = () => (
  <div className="w-full max-w-4xl">
    <AdminTable
      columns={columns}
      getRowKey={(pt) => pt.slug}
      loading
      onDelete={() => {}}
      rows={[]}
      skeletonRows={4}
    />
  </div>
)

export const Empty = () => (
  <div className="w-full max-w-4xl">
    <AdminTable
      columns={columns}
      emptyMessage="No project types in AWeber yet."
      getRowKey={(pt) => pt.slug}
      onDelete={() => {}}
      rows={[]}
    />
  </div>
)

export const ReadOnly = () => (
  <div className="w-full max-w-4xl">
    <AdminTable
      columns={columns.slice(0, 3)}
      getRowKey={(pt) => pt.slug}
      rows={projectTypes.slice(0, 3)}
    />
  </div>
)
