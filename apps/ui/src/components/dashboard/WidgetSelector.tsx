import { X } from 'lucide-react'

import { Button } from '@/components/ui/button'

export interface WidgetConfig {
  category: 'activity' | 'development' | 'health' | 'overview' | 'stats'
  columnSpan?: 1 | 2 | 4 // Number of columns to span in 4-column grid
  description: string
  icon: string
  id: string
  name: string
}

interface WidgetSelectorProps {
  availableWidgets: WidgetConfig[]
  onClose: () => void
  onToggleWidget: (widgetId: string) => void
  selectedWidgets: string[]
}

export function WidgetSelector({
  availableWidgets,
  onClose,
  onToggleWidget,
  selectedWidgets,
}: WidgetSelectorProps) {
  const categories = {
    activity: 'Activity & Events',
    development: 'Development',
    health: 'Health & Monitoring',
    overview: 'Overview & Stats',
    stats: 'Statistics',
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
        aria-labelledby="widget-selector-title"
        aria-modal="true"
        className="max-h-[80vh] w-full max-w-2xl rounded-lg border border-border bg-card shadow-xl"
        role="dialog"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-tertiary p-6">
          <div>
            <h2 className="text-xl text-primary" id="widget-selector-title">
              Customize Dashboard
            </h2>
            <p className="mt-1 text-sm text-secondary">
              Select which widgets to display on your dashboard
            </p>
          </div>
          <button
            aria-label="Close"
            className="rounded p-2 text-secondary hover:bg-secondary"
            onClick={onClose}
            type="button"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Widget List */}
        <div className="max-h-[60vh] overflow-y-auto p-6">
          {Object.entries(groupedWidgets).map(([category, widgets]) => (
            <div className="mb-6 last:mb-0" key={category}>
              <h3 className="mb-3 text-sm uppercase tracking-wider text-tertiary">
                {categories[category as keyof typeof categories]}
              </h3>
              <div className="space-y-2">
                {widgets.map((widget) => {
                  const isSelected = selectedWidgets.includes(widget.id)
                  return (
                    <button
                      aria-pressed={isSelected}
                      className={`flex w-full items-center gap-3 rounded-lg border p-4 transition-all ${
                        isSelected
                          ? 'border-info bg-info text-primary'
                          : 'border-input bg-background text-secondary hover:border-secondary'
                      }`}
                      key={widget.id}
                      onClick={() => onToggleWidget(widget.id)}
                      type="button"
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
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              d="M5 13l4 4L19 7"
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={3}
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
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onClose}
          >
            Done
          </Button>
        </div>
      </div>
    </div>
  )
}
