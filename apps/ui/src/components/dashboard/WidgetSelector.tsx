import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

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
  onOpenChange: (open: boolean) => void
  onToggleWidget: (widgetId: string) => void
  open: boolean
  selectedWidgets: string[]
}

export function WidgetSelector({
  availableWidgets,
  onOpenChange,
  onToggleWidget,
  open,
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
    <Dialog onOpenChange={onOpenChange} open={open}>
      <DialogContent className="max-h-[80vh] sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Customize Dashboard</DialogTitle>
          <DialogDescription>
            Select which widgets to display on your dashboard
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] overflow-y-auto p-6">
          {Object.entries(groupedWidgets).map(([category, widgets]) => (
            <div className="mb-6 last:mb-0" key={category}>
              <h3 className="text-tertiary mb-3 text-sm tracking-wider uppercase">
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
                      <div className="shrink-0 text-2xl">{widget.icon}</div>
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
                        className={`flex size-5 shrink-0 items-center justify-center rounded border-2 ${
                          isSelected ? 'border-info bg-info' : 'border-input'
                        }`}
                      >
                        {isSelected && (
                          <svg
                            className="size-3 text-white"
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

        <DialogFooter className="justify-between">
          <div className="text-secondary text-sm">
            {selectedWidgets.length} widget
            {selectedWidgets.length !== 1 ? 's' : ''} selected
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={() => onOpenChange(false)}
          >
            Done
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
