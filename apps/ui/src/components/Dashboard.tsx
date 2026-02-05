import { useState, useEffect } from 'react'
import { Settings } from 'lucide-react'
import { Button } from './ui/button'
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

interface DashboardProps {
  onViewChange?: (view: any) => void
  onUserSelect?: (userName: string) => void
  onProjectSelect?: (projectId: string) => void
  isDarkMode: boolean
}

const WIDGET_STORAGE_KEY = 'imbi-dashboard-widgets-v3'

const availableWidgets: WidgetConfig[] = [
  {
    id: 'stat-total-projects',
    name: 'Total Projects',
    description: 'Total number of projects',
    icon: '📁',
    category: 'stats',
    columnSpan: 1
  },
  {
    id: 'stat-active-deployments',
    name: 'Active Deployments',
    description: 'Number of active deployments',
    icon: '🚀',
    category: 'stats',
    columnSpan: 1
  },
  {
    id: 'stat-teams',
    name: 'Teams',
    description: 'Total number of teams',
    icon: '👥',
    category: 'stats',
    columnSpan: 1
  },
  {
    id: 'stat-namespaces',
    name: 'Namespaces',
    description: 'Total number of namespaces',
    icon: '📦',
    category: 'stats',
    columnSpan: 1
  },
  {
    id: 'team-activity',
    name: 'Team Activity',
    description: 'Overview of team projects and deployments',
    icon: '👥',
    category: 'activity',
    columnSpan: 2
  },
  {
    id: 'recent-activity',
    name: 'Recent Activity',
    description: 'Latest actions and updates across projects',
    icon: '📝',
    category: 'activity',
    columnSpan: 2
  },
  {
    id: 'recent-deployments',
    name: 'Recent Deployments',
    description: 'Latest deployment activity across environments',
    icon: '🚀',
    category: 'activity',
    columnSpan: 2
  },
  {
    id: 'my-pull-requests',
    name: 'My Pull Requests',
    description: 'Your pending code reviews and PR status',
    icon: '🔀',
    category: 'development',
    columnSpan: 2
  },
  {
    id: 'outdated-components',
    name: 'Outdated Components',
    description: 'Dependencies that need updating',
    icon: '📦',
    category: 'health',
    columnSpan: 2
  }
]

const defaultWidgets = [
  'stat-total-projects',
  'stat-active-deployments',
  'stat-teams',
  'stat-namespaces',
  'team-activity',
  'recent-activity',
  'my-pull-requests'
]

interface SortableWidgetProps {
  id: string
  children: React.ReactNode
  isDarkMode: boolean
}

function SortableWidget({ id, children, isDarkMode }: SortableWidgetProps) {
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
      className="group relative break-inside-avoid mb-4"
    >
      {/* Drag handle - appears on hover */}
      <div
        {...attributes}
        {...listeners}
        className={`absolute top-2 left-2 z-20 p-1 rounded cursor-grab active:cursor-grabbing opacity-0 group-hover:opacity-100 transition-opacity ${
          isDarkMode ? 'bg-gray-700/80 text-gray-400 hover:text-gray-200' : 'bg-white/80 text-gray-400 hover:text-gray-600'
        }`}
      >
        <svg className="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
          <path d="M8 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM8 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM8 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM14 6a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM14 12a2 2 0 1 1-4 0 2 2 0 0 1 4 0zM14 18a2 2 0 1 1-4 0 2 2 0 0 1 4 0z" />
        </svg>
      </div>
      {children}
    </div>
  )
}

export function Dashboard({ onViewChange, onUserSelect, onProjectSelect, isDarkMode }: DashboardProps) {
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
    })
  )

  // Fetch real data for stats
  const { data: projects } = useQuery({
    queryKey: ['projects'],
    queryFn: () => getProjects(),
  })

  const projectCount = projects?.length || 0
  const namespaceCount = projects ? new Set(projects.map(p => p.namespace)).size : 0

  // Persist selections
  useEffect(() => {
    localStorage.setItem(WIDGET_STORAGE_KEY, JSON.stringify(selectedWidgets))
  }, [selectedWidgets])

  const handleToggleWidget = (widgetId: string) => {
    setSelectedWidgets(prev =>
      prev.includes(widgetId)
        ? prev.filter(id => id !== widgetId)
        : [...prev, widgetId]
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
        return <StatWidget title="Total Projects" value={projectCount.toLocaleString()} icon="📁" isDarkMode={isDarkMode} />
      case 'stat-active-deployments':
        return <StatWidget title="Active Deployments" value="1,429" icon="🚀" isDarkMode={isDarkMode} />
      case 'stat-teams':
        return <StatWidget title="Teams" value="11" icon="👥" isDarkMode={isDarkMode} />
      case 'stat-namespaces':
        return <StatWidget title="Namespaces" value={namespaceCount.toLocaleString()} icon="📦" isDarkMode={isDarkMode} />
      case 'team-activity':
        return <TeamActivityWidget isDarkMode={isDarkMode} onViewChange={onViewChange} />
      case 'recent-activity':
        return <RecentActivityWidget isDarkMode={isDarkMode} onUserSelect={onUserSelect} onProjectSelect={onProjectSelect} />
      case 'recent-deployments':
        return <RecentDeploymentsWidget isDarkMode={isDarkMode} onProjectSelect={onProjectSelect} />
      case 'my-pull-requests':
        return <MyPullRequestsWidget isDarkMode={isDarkMode} onUserSelect={onUserSelect} />
      case 'outdated-components':
        return <OutdatedComponentsWidget isDarkMode={isDarkMode} onProjectSelect={onProjectSelect} />
      default:
        return null
    }
  }

  // Separate stat widgets from other widgets for layout
  const statWidgets = selectedWidgets.filter(id => id.startsWith('stat-'))
  const otherWidgets = selectedWidgets.filter(id => !id.startsWith('stat-'))

  return (
    <div className="max-w-[1400px] mx-auto px-6 py-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className={`text-3xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Dashboard
          </h1>
          <p className={`mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Welcome back! Here's what's happening across your projects.
          </p>
        </div>
        <Button
          onClick={() => setShowWidgetSelector(true)}
          variant="outline"
          className={`gap-2 ${isDarkMode ? 'border-gray-600 text-gray-300' : ''}`}
        >
          <Settings className="w-4 h-4" />
          Customize
        </Button>
      </div>

      {/* Widgets */}
      {selectedWidgets.length === 0 ? (
        <div className={`p-12 rounded-lg border text-center ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-6xl mb-4 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`}>
            📊
          </div>
          <h3 className={`text-xl font-medium mb-2 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            No Widgets Selected
          </h3>
          <p className={`max-w-md mx-auto mb-4 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Customize your dashboard by selecting widgets to display
          </p>
          <Button
            onClick={() => setShowWidgetSelector(true)}
            className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
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
              <SortableContext items={statWidgets} strategy={rectSortingStrategy}>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {statWidgets.map((widgetId) => (
                    <SortableWidget key={widgetId} id={widgetId} isDarkMode={isDarkMode}>
                      {renderWidget(widgetId)}
                    </SortableWidget>
                  ))}
                </div>
              </SortableContext>
            )}

            {/* Other widgets - CSS columns for true masonry */}
            {otherWidgets.length > 0 && (
              <SortableContext items={otherWidgets} strategy={rectSortingStrategy}>
                <div
                  className="columns-1 md:columns-2 gap-4"
                  style={{ columnFill: 'balance' }}
                >
                  {otherWidgets.map((widgetId) => (
                    <SortableWidget key={widgetId} id={widgetId} isDarkMode={isDarkMode}>
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
          isDarkMode={isDarkMode}
        />
      )}
    </div>
  )
}
