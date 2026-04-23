import { useState, useEffect } from 'react'
import { Settings } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from '@dnd-kit/core'
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  rectSortingStrategy,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { WidgetSelector, WidgetConfig } from './dashboard/WidgetSelector'
import { StatWidget } from './dashboard/widgets/StatWidget'
import { TeamActivityWidget } from './dashboard/widgets/TeamActivityWidget'
import { RecentActivityWidget } from './dashboard/widgets/RecentActivityWidget'
import { MyPullRequestsWidget } from './dashboard/widgets/MyPullRequestsWidget'
import { OutdatedComponentsWidget } from './dashboard/widgets/OutdatedComponentsWidget'
import { RecentDeploymentsWidget } from './dashboard/widgets/RecentDeploymentsWidget'
import { useQuery } from '@tanstack/react-query'
import { getProjects } from '@/api/endpoints'
import { useOrganization } from '@/contexts/OrganizationContext'

interface ViewChangeEvent {
  view: string
  filter: Record<string, string>
}

interface DashboardProps {
  onViewChange?: (view: ViewChangeEvent) => void
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectId: string) => void
}

const WIDGET_STORAGE_KEY = 'imbi-dashboard-widgets-v3'

const availableWidgets: WidgetConfig[] = [
  {
    id: 'stat-total-projects',
    name: 'Total Projects',
    description: 'Total number of projects',
    icon: '📁',
    category: 'stats',
    columnSpan: 1,
  },
  {
    id: 'stat-active-deployments',
    name: 'Active Deployments',
    description: 'Number of active deployments',
    icon: '🚀',
    category: 'stats',
    columnSpan: 1,
  },
  {
    id: 'stat-teams',
    name: 'Teams',
    description: 'Total number of teams',
    icon: '👥',
    category: 'stats',
    columnSpan: 1,
  },
  {
    id: 'team-activity',
    name: 'Team Activity',
    description: 'Overview of team projects and deployments',
    icon: '👥',
    category: 'activity',
    columnSpan: 2,
  },
  {
    id: 'recent-activity',
    name: 'Recent Activity',
    description: 'Latest actions and updates across projects',
    icon: '📝',
    category: 'activity',
    columnSpan: 2,
  },
  {
    id: 'recent-deployments',
    name: 'Recent Deployments',
    description: 'Latest deployment activity across environments',
    icon: '🚀',
    category: 'activity',
    columnSpan: 2,
  },
  {
    id: 'my-pull-requests',
    name: 'My Pull Requests',
    description: 'Your pending code reviews and PR status',
    icon: '🔀',
    category: 'development',
    columnSpan: 2,
  },
  {
    id: 'outdated-components',
    name: 'Outdated Components',
    description: 'Dependencies that need updating',
    icon: '📦',
    category: 'health',
    columnSpan: 2,
  },
]

const defaultWidgets = [
  'stat-total-projects',
  'stat-active-deployments',
  'stat-teams',
  'team-activity',
  'recent-activity',
  'my-pull-requests',
]

interface SortableWidgetProps {
  id: string
  children: React.ReactNode
}

function SortableWidget({ id, children }: SortableWidgetProps) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      className="group relative mb-4 break-inside-avoid"
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

export function Dashboard({
  onViewChange,
  onUserSelect,
  onProjectSelect,
}: DashboardProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const [showWidgetSelector, setShowWidgetSelector] = useState(false)

  const [selectedWidgets, setSelectedWidgets] = useState<string[]>(() => {
    const stored = localStorage.getItem(WIDGET_STORAGE_KEY)
    if (stored) {
      try {
        return JSON.parse(stored)
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
    queryKey: ['projects', orgSlug],
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    enabled: !!orgSlug,
  })

  const projectCount = projects?.length || 0
  const teamCount = projects
    ? new Set(projects.map((p) => p.team.slug)).size
    : 0

  // Persist selections
  useEffect(() => {
    localStorage.setItem(WIDGET_STORAGE_KEY, JSON.stringify(selectedWidgets))
  }, [selectedWidgets])

  const handleToggleWidget = (widgetId: string) => {
    setSelectedWidgets((prev) =>
      prev.includes(widgetId)
        ? prev.filter((id) => id !== widgetId)
        : [...prev, widgetId],
    )
  }

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event

    if (over && active.id !== over.id) {
      setSelectedWidgets((items) => {
        const oldIndex = items.indexOf(active.id as string)
        const newIndex = items.indexOf(over.id as string)
        return arrayMove(items, oldIndex, newIndex)
      })
    }
  }

  const renderWidget = (widgetId: string) => {
    switch (widgetId) {
      case 'stat-total-projects':
        return (
          <StatWidget
            title="Total Projects"
            value={projectCount.toLocaleString()}
            icon="📁"
          />
        )
      case 'stat-active-deployments':
        return <StatWidget title="Active Deployments" value="1,429" icon="🚀" />
      case 'stat-teams':
        return (
          <StatWidget
            title="Teams"
            value={teamCount.toLocaleString()}
            icon="👥"
          />
        )
      case 'team-activity':
        return <TeamActivityWidget onViewChange={onViewChange} />
      case 'recent-activity':
        return (
          <RecentActivityWidget
            onUserSelect={onUserSelect}
            onProjectSelect={onProjectSelect}
          />
        )
      case 'recent-deployments':
        return <RecentDeploymentsWidget onProjectSelect={onProjectSelect} />
      case 'my-pull-requests':
        return <MyPullRequestsWidget onUserSelect={onUserSelect} />
      case 'outdated-components':
        return <OutdatedComponentsWidget onProjectSelect={onProjectSelect} />
      default:
        return null
    }
  }

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
          onClick={() => setShowWidgetSelector(true)}
          variant="outline"
          className="gap-2"
        >
          <Settings className="h-4 w-4" />
          Customize
        </Button>
      </div>

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
            onClick={() => setShowWidgetSelector(true)}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            Add Widgets
          </Button>
        </div>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          onDragEnd={handleDragEnd}
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
                    <SortableWidget key={widgetId} id={widgetId}>
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
                    <SortableWidget key={widgetId} id={widgetId}>
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
          selectedWidgets={selectedWidgets}
          onToggleWidget={handleToggleWidget}
          onClose={() => setShowWidgetSelector(false)}
        />
      )}
    </div>
  )
}
