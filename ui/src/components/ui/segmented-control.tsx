import * as React from 'react'

import { cn } from '@/lib/utils'

interface SegmentedControlContextValue {
  onValueChange: (value: string) => void
  value: string
}

interface SegmentedControlItemProps extends Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  'value'
> {
  value: string
}

interface SegmentedControlProps extends Omit<
  React.HTMLAttributes<HTMLDivElement>,
  'onChange'
> {
  ariaLabel?: string
  onValueChange: (value: string) => void
  value: string
}

const SegmentedControlContext =
  React.createContext<null | SegmentedControlContextValue>(null)

function useSegmentedControl() {
  const ctx = React.useContext(SegmentedControlContext)
  if (!ctx) {
    throw new Error(
      'SegmentedControlItem must be rendered inside a <SegmentedControl>',
    )
  }
  return ctx
}

const SegmentedControl = React.forwardRef<
  HTMLDivElement,
  SegmentedControlProps
>(({ ariaLabel, children, className, onValueChange, value, ...props }, ref) => (
  <SegmentedControlContext.Provider value={{ onValueChange, value }}>
    <div
      aria-label={ariaLabel}
      className={cn(
        'inline-flex items-center rounded-md border border-tertiary bg-secondary p-0.5',
        className,
      )}
      ref={ref}
      role="radiogroup"
      {...props}
    >
      {children}
    </div>
  </SegmentedControlContext.Provider>
))
SegmentedControl.displayName = 'SegmentedControl'

const SegmentedControlItem = React.forwardRef<
  HTMLButtonElement,
  SegmentedControlItemProps
>(({ children, className, value, ...props }, ref) => {
  const { onValueChange, value: groupValue } = useSegmentedControl()
  const active = groupValue === value
  return (
    <button
      aria-checked={active}
      className={cn(
        'inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs font-medium transition-colors',
        active
          ? 'bg-primary text-primary shadow-sm'
          : 'text-secondary hover:text-primary',
        className,
      )}
      onClick={() => onValueChange(value)}
      ref={ref}
      role="radio"
      type="button"
      {...props}
    >
      {children}
    </button>
  )
})
SegmentedControlItem.displayName = 'SegmentedControlItem'

export { SegmentedControl, SegmentedControlItem }
