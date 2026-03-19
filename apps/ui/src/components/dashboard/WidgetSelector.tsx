import { X } from 'lucide-react'
import { Button } from '@/components/ui/button'

interface WidgetSelectorProps {
  availableWidgets: WidgetConfig[]
  selectedWidgets: string[]
  onToggleWidget: (widgetId: string) => void
  onClose: () => void
  isDarkMode: boolean
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
  isDarkMode,
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
        className={`max-h-[80vh] w-full max-w-2xl rounded-lg shadow-xl ${
          isDarkMode
            ? 'border border-gray-700 bg-gray-800'
            : 'border border-gray-200 bg-white'
        }`}
      >
        {/* Header */}
        <div
          className={`flex items-center justify-between border-b p-6 ${
            isDarkMode ? 'border-gray-700' : 'border-gray-200'
          }`}
        >
          <div>
            <h2
              id="widget-selector-title"
              className={`text-xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
            >
              Customize Dashboard
            </h2>
            <p
              className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
            >
              Select which widgets to display on your dashboard
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            type="button"
            className={`rounded p-2 ${
              isDarkMode
                ? 'text-gray-400 hover:bg-gray-700'
                : 'text-gray-600 hover:bg-gray-100'
            }`}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Widget List */}
        <div className="max-h-[60vh] overflow-y-auto p-6">
          {Object.entries(groupedWidgets).map(([category, widgets]) => (
            <div key={category} className="mb-6 last:mb-0">
              <h3
                className={`mb-3 text-sm uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}
              >
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
                          ? isDarkMode
                            ? 'border-blue-500 bg-blue-900/20 text-white'
                            : 'border-[#2A4DD0] bg-blue-50 text-gray-900'
                          : isDarkMode
                            ? 'bg-gray-750 border-gray-600 text-gray-300 hover:border-gray-500'
                            : 'border-gray-200 bg-white text-gray-700 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex-shrink-0 text-2xl">
                        {widget.icon}
                      </div>
                      <div className="flex-1 text-left">
                        <div
                          className={`font-medium ${isSelected ? (isDarkMode ? 'text-white' : 'text-gray-900') : ''}`}
                        >
                          {widget.name}
                        </div>
                        <div
                          className={`text-sm ${
                            isSelected
                              ? isDarkMode
                                ? 'text-blue-300'
                                : 'text-blue-700'
                              : 'text-gray-500'
                          }`}
                        >
                          {widget.description}
                        </div>
                      </div>
                      <div
                        className={`flex h-5 w-5 flex-shrink-0 items-center justify-center rounded border-2 ${
                          isSelected
                            ? isDarkMode
                              ? 'border-blue-500 bg-blue-500'
                              : 'border-[#2A4DD0] bg-[#2A4DD0]'
                            : isDarkMode
                              ? 'border-gray-500'
                              : 'border-gray-300'
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
        <div
          className={`flex items-center justify-between border-t p-6 ${
            isDarkMode ? 'border-gray-700' : 'border-gray-200'
          }`}
        >
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            {selectedWidgets.length} widget
            {selectedWidgets.length !== 1 ? 's' : ''} selected
          </div>
          <Button
            onClick={onClose}
            className="bg-[#2A4DD0] text-white hover:bg-blue-700"
          >
            Done
          </Button>
        </div>
      </div>
    </div>
  )
}
