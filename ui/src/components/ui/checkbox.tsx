import * as React from 'react'

import * as CheckboxPrimitive from '@radix-ui/react-checkbox'
import { Check, Minus } from 'lucide-react'

import { cn } from '@/lib/utils'

const Checkbox = React.forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ checked, className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    checked={checked}
    className={cn(
      'peer size-4 shrink-0 rounded-sm border border-input ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:border-action data-[state=checked]:bg-action data-[state=checked]:text-action-foreground data-[state=indeterminate]:border-input data-[state=indeterminate]:bg-input data-[state=indeterminate]:text-action-foreground',
      className,
    )}
    ref={ref}
    {...props}
  >
    <CheckboxPrimitive.Indicator
      className={cn('flex items-center justify-center text-current')}
    >
      {checked === 'indeterminate' ? (
        <Minus className="size-3" />
      ) : (
        <Check className="size-3" />
      )}
    </CheckboxPrimitive.Indicator>
  </CheckboxPrimitive.Root>
))
Checkbox.displayName = CheckboxPrimitive.Root.displayName

export { Checkbox }
