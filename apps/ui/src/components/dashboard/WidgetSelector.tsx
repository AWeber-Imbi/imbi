import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface WidgetSelectorProps {
  availableWidgets: WidgetConfig[]
  selectedWidgets: string[]
  onToggleWidget: (widgetId: string) => void
  onClose: () => void
}

export interface WidgetConfig {
  id: string
  name: string
  description: string
  icon: string
  category: 'stats' | 'overview' | 'activity' | 'health' | 'development'
  columnSpan?: 1 | 2 | 4 // Number of columns to span in 4-column grid
}

export function WidgetSelector({
  availableWidgets,
  selectedWidgets,
  onToggleWidget,
  onClose,
}: WidgetSelectorProps) {
  const categories = {
    stats: 'Statistics',
    overview: 'Overview & Stats',
    activity: 'Activity & Events',
    health: 'Health & Monitoring',
    development: 'Development',
  }

  const groupedWidgets = availableWidgets.reduce(
    (acc, widget) => {
      if (!acc[widget.category]) {
        acc[widget.category] = []
      }
      acc[widget.category].push(widget)
      return acc
    },
    {} as Record<string, WidgetConfig[]>,
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="widget-selector-title"
        className="max-h-[80vh] w-full max-w-2xl rounded-lg border border-border bg-card shadow-xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-tertiary p-6">
          <div>
            <h2 id="widget-selector-title" className="text-xl text-primary">
              Customize Dashboard
            </h2>
            <p className="mt-1 text-sm text-secondary">
              Select which widgets to display on your dashboard
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            type="button"
            className="rounded p-2 text-secondary hover:bg-secondary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Widget List */}
        <div className="max-h-[60vh] overflow-y-auto p-6">
          {Object.entries(groupedWidgets).map(([category, widgets]) => (
            <div key={category} className="mb-6 last:mb-0">
              <h3 className="mb-3 text-sm uppercase tracking-wider text-tertiary">
                {categories[category as keyof typeof categories]}
              </h3>
              <div className="space-y-2">
                {widgets.map((widget) => {
                  const isSelected = selectedWidgets.includes(widget.id)
                  return (
                    <button
                      key={widget.id}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() => onToggleWidget(widget.id)}
                      className={`flex w-full items-center gap-3 rounded-lg border p-4 transition-all ${
                        isSelected
                          ? 'border-info bg-info text-primary'
                          : 'border-input bg-background text-secondary hover:border-secondary'
                      }`}
                    >
                      <div className="flex-shrink-0 text-2xl">
                        {widget.icon}
                      </div>
                      <div className="flex-1 text-left">
                        <div
                          className={`font-medium ${isSelected ? 'text-primary' : ''}`}
                        >
                          {widget.name}
                        </div>
                        <div
                          className={`text-sm ${
                            isSelected ? 'text-info' : 'text-tertiary'
                          }`}
                        >
                          {widget.description}
                        </div>
                      </div>
                      <div
                        className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded border-2 ${
                          isSelected ? 'border-info bg-info' : 'border-input'
                        }`}
                      >
                        {isSelected && (
                          <svg
                            className="h-3 w-3 text-white"
                            fill="none"
                            viewBox="0 0 24 24"
                            stroke="currentColor"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={3}
                              d="M5 13l4 4L19 7"
                            />
                          </svg>
                        )}
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          ))}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-tertiary p-6">
          <div className="text-sm text-secondary">
            {selectedWidgets.length} widget
            {selectedWidgets.length !== 1 ? 's' : ''} selected
          </div>
          <Button
            onClick={onClose}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            Done
          </Button>
        </div>
      </div>
    </div>
  )
}
