import { type ReactElement, useEffect, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import {
  closestCenter,
  DndContext,
  DragEndEvent,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
} from '@dnd-kit/core'
import {
  arrayMove,
  rectSortingStrategy,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { useQuery } from '@tanstack/react-query'
import { Settings } from 'lucide-react'

import { getAdminPlugins, getMyIdentities, getProjects } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useRecentDeployments } from '@/hooks/useRecentDeployments'
import { queryKeys } from '@/lib/queryKeys'
import type { AdminPluginsResponse, IdentityConnectionResponse } from '@/types'

import { MyPullRequestsWidget } from './dashboard/widgets/MyPullRequestsWidget'
import { OutdatedComponentsWidget } from './dashboard/widgets/OutdatedComponentsWidget'
import { RecentActivityWidget } from './dashboard/widgets/RecentActivityWidget'
import { RecentDeploymentsWidget } from './dashboard/widgets/RecentDeploymentsWidget'
import { StatWidget } from './dashboard/widgets/StatWidget'
import { TeamActivityWidget } from './dashboard/widgets/TeamActivityWidget'
import { UnconnectedIntegrationWidget } from './dashboard/widgets/UnconnectedIntegrationWidget'
import { WidgetConfig, WidgetSelector } from './dashboard/WidgetSelector'

interface DashboardProps {
  onProjectSelect?: (projectId: string) => void
  onUserSelect?: (userName: string) => void
  onViewChange?: (view: ViewChangeEvent) => void
}

interface ViewChangeEvent {
  filter: Record<string, string>
  view: string
}

const WIDGET_STORAGE_KEY = 'imbi-dashboard-widgets-v3'

type WidgetId =
  | 'my-pull-requests'
  | 'outdated-components'
  | 'recent-activity'
  | 'recent-deployments'
  | 'stat-active-deployments'
  | 'stat-teams'
  | 'stat-total-projects'
  | 'team-activity'

const availableWidgets: WidgetConfig[] = [
  {
    category: 'stats',
    columnSpan: 1,
    description: 'Total number of projects',
    icon: '📁',
    id: 'stat-total-projects',
    name: 'Total Projects',
  },
  {
    category: 'stats',
    columnSpan: 1,
    description: 'Number of active deployments',
    icon: '🚀',
    id: 'stat-active-deployments',
    name: 'Active Deployments',
  },
  {
    category: 'stats',
    columnSpan: 1,
    description: 'Total number of teams',
    icon: '👥',
    id: 'stat-teams',
    name: 'Teams',
  },
  {
    category: 'activity',
    columnSpan: 2,
    description: 'Overview of team projects and deployments',
    icon: '👥',
    id: 'team-activity',
    name: 'Team Activity',
  },
  {
    category: 'activity',
    columnSpan: 2,
    description: 'Latest actions and updates across projects',
    icon: '📝',
    id: 'recent-activity',
    name: 'Recent Activity',
  },
  {
    category: 'activity',
    columnSpan: 2,
    description: 'Latest deployment activity across environments',
    icon: '🚀',
    id: 'recent-deployments',
    name: 'Recent Deployments',
  },
  {
    category: 'development',
    columnSpan: 2,
    description: 'Your pending code reviews and PR status',
    icon: '🔀',
    id: 'my-pull-requests',
    name: 'My Pull Requests',
  },
  {
    category: 'health',
    columnSpan: 2,
    description: 'Dependencies that need updating',
    icon: '📦',
    id: 'outdated-components',
    name: 'Outdated Components',
  },
]

const defaultWidgets: WidgetId[] = [
  'stat-total-projects',
  'stat-active-deployments',
  'stat-teams',
  'team-activity',
  'recent-activity',
  'my-pull-requests',
]

const WIDGET_IDS: ReadonlySet<WidgetId> = new Set<WidgetId>([
  'my-pull-requests',
  'outdated-components',
  'recent-activity',
  'recent-deployments',
  'stat-active-deployments',
  'stat-teams',
  'stat-total-projects',
  'team-activity',
])

const isWidgetId = (value: unknown): value is WidgetId =>
  typeof value === 'string' && WIDGET_IDS.has(value as WidgetId)

interface SortableWidgetProps {
  children: React.ReactNode
  id: string
}

export function Dashboard({
  onProjectSelect,
  onUserSelect,
  onViewChange,
}: DashboardProps) {
  const navigate = useNavigate()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const [showWidgetSelector, setShowWidgetSelector] = useState(false)

  // Identity plugins the actor hasn't connected yet drive the
  // dashboard's "unconnected integration" widgets.  These can't be
  // dismissed — they disappear automatically once the connection
  // becomes active.
  const pluginsQuery = useQuery<AdminPluginsResponse>({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: queryKeys.adminPlugins(),
    staleTime: 60 * 1000,
  })
  const identitiesQuery = useQuery<IdentityConnectionResponse[]>({
    queryFn: ({ signal }) => getMyIdentities(signal),
    queryKey: ['me-identities'],
    staleTime: 0,
  })

  const connectedSlugs = new Set(
    (identitiesQuery.data ?? [])
      .filter((c) => c.status === 'active')
      .map((c) => c.plugin_slug),
  )
  const unconnectedIdentityPlugins = (
    pluginsQuery.data?.installed ?? []
  ).filter(
    (p) =>
      p.enabled && p.plugin_type === 'identity' && !connectedSlugs.has(p.slug),
  )

  const [selectedWidgets, setSelectedWidgets] = useState<WidgetId[]>(() => {
    const stored = localStorage.getItem(WIDGET_STORAGE_KEY)
    if (stored) {
      try {
        const parsed: unknown = JSON.parse(stored)
        if (Array.isArray(parsed)) {
          return Array.from(new Set(parsed.filter(isWidgetId)))
        }
        return defaultWidgets
      } catch {
        return defaultWidgets
      }
    }
    return defaultWidgets
  })

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    }),
  )

  // Fetch real data for stats
  const { data: projects } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  const projectCount = projects?.length || 0
  const teamCount = projects
    ? new Set(projects.map((p) => p.team.slug)).size
    : 0

  const {
    data: recentDeployments,
    isError: isDeploymentsError,
    isLoading: isDeploymentsLoading,
  } = useRecentDeployments(orgSlug, 50)
  // TODO(active-count): This counts active deployments within the latest
  // 50 operations-log entries — it undercounts when more than 50 active
  // deployments exist. Replace with a dedicated server-side count endpoint
  // (e.g. GET /operations-log/count?action=deployed&completed_at=null) once
  // imbi-api exposes one. Adding that endpoint is out of scope for this PR.
  const activeDeploymentCount = (recentDeployments ?? []).filter(
    (d) => d.completed_at == null,
  ).length

  // Persist selections
  useEffect(() => {
    localStorage.setItem(WIDGET_STORAGE_KEY, JSON.stringify(selectedWidgets))
  }, [selectedWidgets])

  const handleToggleWidget = (widgetId: string) => {
    if (!isWidgetId(widgetId)) return
    setSelectedWidgets((prev) =>
      prev.includes(widgetId)
        ? prev.filter((id) => id !== widgetId)
        : [...prev, widgetId],
    )
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event

    if (over && active.id !== over.id) {
      if (!isWidgetId(active.id) || !isWidgetId(over.id)) return
      const activeId = active.id
      const overId = over.id
      setSelectedWidgets((items) => {
        const oldIndex = items.indexOf(activeId)
        const newIndex = items.indexOf(overId)
        if (oldIndex === -1 || newIndex === -1) return items
        return arrayMove(items, oldIndex, newIndex)
      })
    }
  }

  const widgetRegistry: Record<WidgetId, () => ReactElement> = {
    'my-pull-requests': () => (
      <MyPullRequestsWidget onUserSelect={onUserSelect} />
    ),
    'outdated-components': () => (
      <OutdatedComponentsWidget onProjectSelect={onProjectSelect} />
    ),
    'recent-activity': () => (
      <RecentActivityWidget
        onProjectSelect={onProjectSelect}
        onUserSelect={onUserSelect}
      />
    ),
    'recent-deployments': () => (
      <RecentDeploymentsWidget onProjectSelect={onProjectSelect} />
    ),
    'stat-active-deployments': () => (
      <StatWidget
        icon="🚀"
        isError={isDeploymentsError}
        isLoading={isDeploymentsLoading}
        title="Active Deployments"
        value={activeDeploymentCount.toLocaleString()}
      />
    ),
    'stat-teams': () => (
      <StatWidget icon="👥" title="Teams" value={teamCount.toLocaleString()} />
    ),
    'stat-total-projects': () => (
      <StatWidget
        icon="📁"
        title="Total Projects"
        value={projectCount.toLocaleString()}
      />
    ),
    'team-activity': () => <TeamActivityWidget onViewChange={onViewChange} />,
  }

  const renderWidget = (widgetId: WidgetId) => widgetRegistry[widgetId]()

  // Separate stat widgets from other widgets for layout
  const statWidgets = selectedWidgets.filter((id) => id.startsWith('stat-'))
  const otherWidgets = selectedWidgets.filter((id) => !id.startsWith('stat-'))

  return (
    <div className="mx-auto max-w-[1400px] px-6 py-8">
      {/* Header */}
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-semibold text-primary">Dashboard</h1>
          <p className="mt-1 text-secondary">
            Welcome back! Here's what's happening across your projects.
          </p>
        </div>
        <Button
          className="gap-2"
          onClick={() => setShowWidgetSelector(true)}
          variant="outline"
        >
          <Settings className="h-4 w-4" />
          Customize
        </Button>
      </div>

      {/* Unconnected-integration widgets — non-dismissable; disappear
          automatically when the matching connection becomes active. */}
      {unconnectedIdentityPlugins.length > 0 && (
        <div className="mb-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          {unconnectedIdentityPlugins.map((plugin) => (
            <UnconnectedIntegrationWidget
              key={plugin.slug}
              onConnect={() =>
                navigate(
                  `/settings/connections?connect=${encodeURIComponent(plugin.slug)}`,
                )
              }
              onManage={() => navigate('/settings/connections')}
              pending={false}
              plugin={plugin}
            />
          ))}
        </div>
      )}

      {/* Widgets */}
      {selectedWidgets.length === 0 ? (
        <div className="rounded-lg border border-border bg-card p-12 text-center">
          <div className="mb-4 text-6xl text-secondary">📊</div>
          <h3 className="mb-2 text-xl font-medium text-primary">
            No Widgets Selected
          </h3>
          <p className="mx-auto mb-4 max-w-md text-secondary">
            Customize your dashboard by selecting widgets to display
          </p>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={() => setShowWidgetSelector(true)}
          >
            Add Widgets
          </Button>
        </div>
      ) : (
        <DndContext
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
          sensors={sensors}
        >
          <div className="space-y-4">
            {/* Stats Row - always in a grid row, also sortable */}
            {statWidgets.length > 0 && (
              <SortableContext
                items={statWidgets}
                strategy={rectSortingStrategy}
              >
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  {statWidgets.map((widgetId) => (
                    <SortableWidget id={widgetId} key={widgetId}>
                      {renderWidget(widgetId)}
                    </SortableWidget>
                  ))}
                </div>
              </SortableContext>
            )}

            {/* Other widgets - CSS columns for true masonry */}
            {otherWidgets.length > 0 && (
              <SortableContext
                items={otherWidgets}
                strategy={rectSortingStrategy}
              >
                <div
                  className="columns-1 gap-4 md:columns-2"
                  style={{ columnFill: 'balance' }}
                >
                  {otherWidgets.map((widgetId) => (
                    <SortableWidget id={widgetId} key={widgetId}>
                      {renderWidget(widgetId)}
                    </SortableWidget>
                  ))}
                </div>
              </SortableContext>
            )}
          </div>
        </DndContext>
      )}

      {/* Widget Selector Modal */}
      {showWidgetSelector && (
        <WidgetSelector
          availableWidgets={availableWidgets}
          onClose={() => setShowWidgetSelector(false)}
          onToggleWidget={handleToggleWidget}
          selectedWidgets={selectedWidgets}
        />
      )}
    </div>
  )
}

function SortableWidget({ children, id }: SortableWidgetProps) {
  const {
    attributes,
    isDragging,
    listeners,
    setNodeRef,
    transform,
    transition,
  } = useSortable({ id })

  const style = {
    opacity: isDragging ? 0.5 : 1,
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <div
      className="group relative mb-4 break-inside-avoid"
      ref={setNodeRef}
      style={style}
    >
      {/* Drag handle - appears on hover */}
      <div
        {...attributes}
        {...listeners}
        className="bg-secondary/80 absolute left-2 top-2 z-20 cursor-grab rounded p-1 text-tertiary opacity-0 transition-opacity hover:text-primary active:cursor-grabbing group-hover:opacity-100"
      >
        <svg className="h-4 w-4" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM8 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM14 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM14 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM14 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0z" />
        </svg>
      </div>
      {children}
    </div>
  )
}
