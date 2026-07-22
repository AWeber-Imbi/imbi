import * as React from 'react'

import * as TooltipPrimitive from '@radix-ui/react-tooltip'

import { cn } from '@/lib/utils'

const TooltipProvider = TooltipPrimitive.Provider

const Tooltip = TooltipPrimitive.Root

const TooltipTrigger = TooltipPrimitive.Trigger

const TooltipContent = React.forwardRef<
  React.ElementRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      className={cn(
        'z-50 animate-in overflow-hidden rounded-md border bg-popover px-3 py-1.5 text-sm text-popover-foreground shadow-md fade-in-0 zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=closed]:zoom-out-95',
        className,
      )}
      ref={ref}
      sideOffset={sideOffset}
      {...props}
    />
  </TooltipPrimitive.Portal>
))
TooltipContent.displayName = TooltipPrimitive.Content.displayName

/**
 * One-shot tooltip wrapper for icon buttons. Replaces the native
 * `title=` attribute with a styled, design-system tooltip that also
 * works on touch.
 *
 *   <IconTooltip label="Delete">
 *     <Button onClick={...}><Trash2 /></Button>
 *   </IconTooltip>
 *
 * The child must be a single element that accepts a `ref` (Radix's
 * `asChild` forwards it). Provide an `aria-label` on the child for
 * screen readers — the tooltip text alone is not announced.
 */
function IconTooltip({
  children,
  delayDuration = 200,
  label,
  side,
}: {
  children: React.ReactElement
  delayDuration?: number
  label: React.ReactNode
  side?: 'bottom' | 'left' | 'right' | 'top'
}) {
  return (
    <TooltipProvider delayDuration={delayDuration}>
      <Tooltip>
        <TooltipTrigger asChild>{children}</TooltipTrigger>
        <TooltipContent side={side}>{label}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export { IconTooltip, Tooltip, TooltipContent, TooltipProvider, TooltipTrigger }
