import { X } from 'lucide-react'
import { Button } from '../ui/button'

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

export function WidgetSelector({ availableWidgets, selectedWidgets, onToggleWidget, onClose, isDarkMode }: WidgetSelectorProps) {
  const categories = {
    stats: 'Statistics',
    overview: 'Overview & Stats',
    activity: 'Activity & Events',
    health: 'Health & Monitoring',
    development: 'Development'
  }

  const groupedWidgets = availableWidgets.reduce((acc, widget) => {
    if (!acc[widget.category]) {
      acc[widget.category] = []
    }
    acc[widget.category].push(widget)
    return acc
  }, {} as Record<string, WidgetConfig[]>)

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className={`w-full max-w-2xl max-h-[80vh] rounded-lg shadow-xl ${
        isDarkMode ? 'bg-gray-800 border border-gray-700' : 'bg-white border border-gray-200'
      }`}>
        {/* Header */}
        <div className={`flex items-center justify-between p-6 border-b ${
          isDarkMode ? 'border-gray-700' : 'border-gray-200'
        }`}>
          <div>
            <h2 className={`text-xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              Customize Dashboard
            </h2>
            <p className={`text-sm mt-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              Select which widgets to display on your dashboard
            </p>
          </div>
          <button
            onClick={onClose}
            className={`p-2 rounded ${
              isDarkMode ? 'hover:bg-gray-700 text-gray-400' : 'hover:bg-gray-100 text-gray-600'
            }`}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Widget List */}
        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {Object.entries(groupedWidgets).map(([category, widgets]) => (
            <div key={category} className="mb-6 last:mb-0">
              <h3 className={`text-sm uppercase tracking-wider mb-3 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}>
                {categories[category as keyof typeof categories]}
              </h3>
              <div className="space-y-2">
                {widgets.map((widget) => {
                  const isSelected = selectedWidgets.includes(widget.id)
                  return (
                    <button
                      key={widget.id}
                      onClick={() => onToggleWidget(widget.id)}
                      className={`w-full flex items-center gap-3 p-4 rounded-lg border transition-all ${
                        isSelected
                          ? isDarkMode
                            ? 'bg-blue-900/20 border-blue-500 text-white'
                            : 'bg-blue-50 border-[#2A4DD0] text-gray-900'
                          : isDarkMode
                            ? 'bg-gray-750 border-gray-600 text-gray-300 hover:border-gray-500'
                            : 'bg-white border-gray-200 text-gray-700 hover:border-gray-300'
                      }`}
                    >
                      <div className="flex-shrink-0 text-2xl">{widget.icon}</div>
                      <div className="flex-1 text-left">
                        <div className={`font-medium ${isSelected ? (isDarkMode ? 'text-white' : 'text-gray-900') : ''}`}>
                          {widget.name}
                        </div>
                        <div className={`text-sm ${
                          isSelected
                            ? isDarkMode ? 'text-blue-300' : 'text-blue-700'
                            : isDarkMode ? 'text-gray-500' : 'text-gray-500'
                        }`}>
                          {widget.description}
                        </div>
                      </div>
                      <div className={`flex-shrink-0 w-5 h-5 rounded border-2 flex items-center justify-center ${
                        isSelected
                          ? isDarkMode
                            ? 'bg-blue-500 border-blue-500'
                            : 'bg-[#2A4DD0] border-[#2A4DD0]'
                          : isDarkMode
                            ? 'border-gray-500'
                            : 'border-gray-300'
                      }`}>
                        {isSelected && (
                          <svg className="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
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
        <div className={`flex items-center justify-between p-6 border-t ${
          isDarkMode ? 'border-gray-700' : 'border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {selectedWidgets.length} widget{selectedWidgets.length !== 1 ? 's' : ''} selected
          </div>
          <Button onClick={onClose} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
            Done
          </Button>
        </div>
      </div>
    </div>
  )
}
