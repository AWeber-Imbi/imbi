import * as React from 'react'

import { ChevronRightIcon } from 'lucide-react'

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { cn } from '@/lib/utils'

function Trace({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'flex w-full min-w-0 flex-col gap-2 *:has-[>[data-slot=trace-line]]:flex *:has-[>[data-slot=trace-line]]:w-fit *:has-[>[data-slot=trace-line]]:max-w-full *:has-[>[data-slot=trace-line]]:min-w-0 *:has-[>[data-slot=trace-line]]:rounded-md *:has-[>[data-slot=trace-line]]:text-left *:has-[>[data-slot=trace-line]]:outline-none *:focus-visible:has-[>[data-slot=trace-line]]:ring-3 *:focus-visible:has-[>[data-slot=trace-line]]:ring-ring/50',
        className,
      )}
      data-slot="trace"
      {...props}
    />
  )
}

function TraceCollapsible({
  className,
  ...props
}: Omit<React.ComponentProps<typeof Collapsible>, 'asChild' | 'open'> &
  (
    | {
        onOpenChange: NonNullable<
          React.ComponentProps<typeof Collapsible>['onOpenChange']
        >
        open: boolean
      }
    | { open?: undefined }
  )) {
  return (
    <Collapsible
      className={cn('flex w-full min-w-0 flex-col', className)}
      data-slot="trace-collapsible"
      {...props}
    />
  )
}

function TraceCollapsibleContent({
  children,
  className,
  ...props
}: Omit<React.ComponentProps<typeof CollapsibleContent>, 'asChild'>) {
  return (
    <CollapsibleContent
      className="data-open:animate-accordion-down data-closed:animate-accordion-up min-w-0 overflow-hidden duration-200 [--radix-accordion-content-height:var(--radix-collapsible-content-height)]"
      data-slot="trace-collapsible-content"
      {...props}
    >
      <div
        className={cn(
          'mt-2 mb-1 ml-[calc(--spacing(2)-1px)] min-w-0 border-l pr-1 pl-4 leading-relaxed wrap-break-word text-muted-foreground',
          className,
        )}
        data-slot="trace-collapsible-content-inner"
      >
        {children}
      </div>
    </CollapsibleContent>
  )
}

function TraceCollapsibleTrigger({
  children,
  className,
  ...props
}: Omit<React.ComponentProps<typeof CollapsibleTrigger>, 'asChild'>) {
  return (
    <CollapsibleTrigger
      className={cn(
        'group/trace-collapsible-trigger flex w-fit max-w-full min-w-0 cursor-pointer items-center gap-1 rounded-md text-left text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-3 focus-visible:ring-ring/50 has-[[data-status=error]]:text-destructive',
        className,
      )}
      data-slot="trace-collapsible-trigger"
      {...props}
    >
      {children}
      <TraceIcon className="transition-transform group-aria-expanded/trace-collapsible-trigger:rotate-90">
        <ChevronRightIcon />
      </TraceIcon>
    </CollapsibleTrigger>
  )
}

function TraceDescription({
  className,
  ...props
}: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn(
        'shrink-0 text-muted-foreground/70 tabular-nums',
        className,
      )}
      data-slot="trace-description"
      {...props}
    />
  )
}

function TraceIcon({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex size-4 shrink-0 items-center justify-center [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 [[data-slot=trace-title]~&]:-ml-1",
        className,
      )}
      data-slot="trace-icon"
      {...props}
    />
  )
}

function TraceLine({
  className,
  status,
  ...props
}: React.ComponentProps<'span'> & {
  status?: 'error' | 'pending' | 'running'
}) {
  return (
    <span
      className={cn(
        'flex w-fit max-w-full min-w-0 items-center gap-2 text-sm text-muted-foreground transition-colors in-[a,button]:cursor-pointer in-[a:hover,button:hover]:text-foreground data-[status=error]:text-destructive data-[status=error]:in-[a:hover,button:hover]:text-destructive data-[status=pending]:opacity-60 data-[status=running]:*:data-[slot=trace-title]:shimmer',
        className,
      )}
      data-slot="trace-line"
      data-status={status}
      {...props}
    />
  )
}

function TraceTitle({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span
      className={cn('min-w-0 truncate motion-reduce:shimmer-none', className)}
      data-slot="trace-title"
      {...props}
    />
  )
}

export {
  Trace,
  TraceCollapsible,
  TraceCollapsibleContent,
  TraceCollapsibleTrigger,
  TraceDescription,
  TraceIcon,
  TraceLine,
  TraceTitle,
}
