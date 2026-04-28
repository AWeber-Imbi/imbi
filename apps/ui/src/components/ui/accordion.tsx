import * as React from 'react'

import * as AccordionPrimitive from '@radix-ui/react-accordion'
import { ChevronDown } from 'lucide-react'

import { cn } from '@/lib/utils'

const Accordion = AccordionPrimitive.Root

const AccordionItem = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Item>
>(({ className, ...props }, ref) => (
  <AccordionPrimitive.Item
    className={cn(
      'relative border-b border-tertiary last:border-0 data-[state=open]:bg-secondary',
      // Amber accent bar on the left; visible on hover for closed items and
      // always visible for open items. Rendered via ::before so it overlays
      // children instead of being painted over by the trigger.
      "before:pointer-events-none before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-[theme(colors.amber.border)] before:opacity-0 before:transition-opacity before:content-['']",
      'hover:before:opacity-100 data-[state=open]:before:opacity-100',
      className,
    )}
    ref={ref}
    {...props}
  />
))
AccordionItem.displayName = 'AccordionItem'

const AccordionTrigger = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Trigger> & {
    hideChevron?: boolean
  }
>(({ children, className, hideChevron = false, ...props }, ref) => (
  <AccordionPrimitive.Header className="flex">
    <AccordionPrimitive.Trigger
      className={cn(
        'group flex flex-1 items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-secondary focus:bg-secondary focus:outline-none',
        'data-[state=open]:hover:bg-transparent',
        className,
      )}
      ref={ref}
      {...props}
    >
      {children}
      {!hideChevron && (
        <ChevronDown className="mt-1.5 h-4 w-4 flex-shrink-0 text-tertiary transition-transform duration-200 group-data-[state=open]:rotate-180" />
      )}
    </AccordionPrimitive.Trigger>
  </AccordionPrimitive.Header>
))
AccordionTrigger.displayName = AccordionPrimitive.Trigger.displayName

const AccordionContent = React.forwardRef<
  React.ElementRef<typeof AccordionPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof AccordionPrimitive.Content>
>(({ children, className, ...props }, ref) => (
  <AccordionPrimitive.Content
    className="overflow-hidden text-sm data-[state=closed]:animate-accordion-up data-[state=open]:animate-accordion-down"
    ref={ref}
    {...props}
  >
    <div className={className}>{children}</div>
  </AccordionPrimitive.Content>
))
AccordionContent.displayName = AccordionPrimitive.Content.displayName

export { Accordion, AccordionContent, AccordionItem, AccordionTrigger }
