import * as React from 'react'

import {
  ChevronDownIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
} from 'lucide-react'
import {
  type CustomComponents,
  type DayButton,
  DayPicker,
  getDefaultClassNames,
  type Locale,
} from 'react-day-picker'

import { Button, buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'

function Calendar({
  buttonVariant = 'ghost',
  captionLayout = 'label',
  className,
  classNames,
  components,
  formatters,
  locale,
  showOutsideDays = true,
  ...props
}: React.ComponentProps<typeof DayPicker> & {
  buttonVariant?: React.ComponentProps<typeof Button>['variant']
}) {
  const defaultClassNames = getDefaultClassNames()
  const LocaleDayButton = React.useMemo(
    () =>
      function LocaleDayButton(
        dayProps: React.ComponentProps<typeof DayButton>,
      ) {
        return <CalendarDayButton locale={locale} {...dayProps} />
      },
    [locale],
  )

  return (
    <DayPicker
      captionLayout={captionLayout}
      className={cn(
        'group/calendar bg-background p-2 in-data-[slot=card-content]:bg-transparent in-data-[slot=popover-content]:bg-transparent',
        String.raw`rtl:**:[.rdp-button\_next>svg]:rotate-180`,
        String.raw`rtl:**:[.rdp-button\_previous>svg]:rotate-180`,
        className,
      )}
      classNames={{
        button_next: cn(
          buttonVariants({ variant: buttonVariant }),
          'size-7 p-0 select-none aria-disabled:opacity-50',
          defaultClassNames.button_next,
        ),
        button_previous: cn(
          buttonVariants({ variant: buttonVariant }),
          'size-7 p-0 select-none aria-disabled:opacity-50',
          defaultClassNames.button_previous,
        ),
        caption_label: cn(
          'font-medium select-none',
          captionLayout === 'label'
            ? 'text-sm'
            : 'flex items-center gap-1 rounded-md text-sm [&>svg]:size-3.5 [&>svg]:text-muted-foreground',
          defaultClassNames.caption_label,
        ),
        day: cn(
          'group/day relative aspect-square size-full rounded-md p-0 text-center select-none [&:last-child[data-selected=true]_button]:rounded-r-md',
          props.showWeekNumber
            ? '[&:nth-child(2)[data-selected=true]_button]:rounded-l-md'
            : '[&:first-child[data-selected=true]_button]:rounded-l-md',
          defaultClassNames.day,
        ),
        disabled: cn(
          'text-muted-foreground opacity-50',
          defaultClassNames.disabled,
        ),
        dropdown: cn(
          'absolute inset-0 bg-popover opacity-0',
          defaultClassNames.dropdown,
        ),
        dropdown_root: cn(
          'relative rounded-md',
          defaultClassNames.dropdown_root,
        ),
        dropdowns: cn(
          'flex h-7 w-full items-center justify-center gap-1.5 text-sm font-medium',
          defaultClassNames.dropdowns,
        ),
        hidden: cn('invisible', defaultClassNames.hidden),
        month: cn('flex w-full flex-col gap-4', defaultClassNames.month),
        month_caption: cn(
          'flex h-7 w-full items-center justify-center px-7',
          defaultClassNames.month_caption,
        ),
        month_grid: cn('w-full border-collapse', defaultClassNames.month_grid),
        months: cn(
          'relative flex flex-col gap-4 md:flex-row',
          defaultClassNames.months,
        ),
        nav: cn(
          'absolute inset-x-0 top-0 flex w-full items-center justify-between gap-1',
          defaultClassNames.nav,
        ),
        outside: cn(
          'text-muted-foreground aria-selected:text-muted-foreground',
          defaultClassNames.outside,
        ),
        range_end: cn(
          'relative isolate z-0 rounded-r-md bg-muted after:absolute after:inset-y-0 after:left-0 after:w-4 after:bg-muted',
          defaultClassNames.range_end,
        ),
        range_middle: cn('rounded-none', defaultClassNames.range_middle),
        range_start: cn(
          'relative isolate z-0 rounded-l-md bg-muted after:absolute after:inset-y-0 after:right-0 after:w-4 after:bg-muted',
          defaultClassNames.range_start,
        ),
        root: cn('w-fit', defaultClassNames.root),
        today: cn(
          'rounded-md bg-muted text-foreground data-[selected=true]:rounded-none',
          defaultClassNames.today,
        ),
        week: cn('mt-2 flex w-full', defaultClassNames.week),
        week_number: cn(
          'text-[0.8rem] text-muted-foreground select-none',
          defaultClassNames.week_number,
        ),
        week_number_header: cn(
          'w-7 select-none',
          defaultClassNames.week_number_header,
        ),
        weekday: cn(
          'flex-1 rounded-md text-[0.8rem] font-normal text-muted-foreground select-none',
          defaultClassNames.weekday,
        ),
        weekdays: cn('flex', defaultClassNames.weekdays),
        ...classNames,
      }}
      components={{
        Chevron: CalendarChevron,
        DayButton: LocaleDayButton,
        Root: CalendarRoot,
        WeekNumber: CalendarWeekNumber,
        ...components,
      }}
      formatters={{
        formatMonthDropdown: (date) =>
          date.toLocaleString(locale?.code, { month: 'short' }),
        ...formatters,
      }}
      locale={locale}
      showOutsideDays={showOutsideDays}
      {...props}
    />
  )
}

function CalendarChevron({
  className,
  orientation,
  ...props
}: CustomComponents['Chevron'] extends React.ComponentType<infer P>
  ? P
  : never) {
  const Icon =
    orientation === 'left'
      ? ChevronLeftIcon
      : orientation === 'right'
        ? ChevronRightIcon
        : ChevronDownIcon
  return <Icon className={cn('size-4', className)} {...props} />
}

function CalendarDayButton({
  className,
  day,
  locale,
  modifiers,
  ...props
}: React.ComponentProps<typeof DayButton> & { locale?: Partial<Locale> }) {
  const defaultClassNames = getDefaultClassNames()

  const ref = React.useRef<HTMLButtonElement>(null)
  React.useEffect(() => {
    if (modifiers.focused) ref.current?.focus()
  }, [modifiers.focused])

  return (
    <Button
      className={cn(
        'relative isolate z-10 flex aspect-square size-auto w-full min-w-7 flex-col gap-1 border-0 leading-none font-normal group-data-[focused=true]/day:relative group-data-[focused=true]/day:z-10 group-data-[focused=true]/day:border-ring group-data-[focused=true]/day:ring-[3px] group-data-[focused=true]/day:ring-ring/50 data-[range-end=true]:rounded-md data-[range-end=true]:rounded-r-md data-[range-end=true]:bg-action data-[range-end=true]:text-action-foreground data-[range-middle=true]:rounded-none data-[range-middle=true]:bg-muted data-[range-middle=true]:text-foreground data-[range-start=true]:rounded-md data-[range-start=true]:rounded-l-md data-[range-start=true]:bg-action data-[range-start=true]:text-action-foreground data-[selected-single=true]:bg-action data-[selected-single=true]:text-action-foreground hover:dark:text-foreground [&>span]:text-xs [&>span]:opacity-70',
        defaultClassNames.day,
        className,
      )}
      data-day={day.date.toLocaleDateString(locale?.code)}
      data-range-end={modifiers.range_end}
      data-range-middle={modifiers.range_middle}
      data-range-start={modifiers.range_start}
      data-selected-single={
        modifiers.selected &&
        !modifiers.range_start &&
        !modifiers.range_end &&
        !modifiers.range_middle
      }
      ref={ref}
      size="icon"
      variant="ghost"
      {...props}
    />
  )
}

function CalendarRoot({
  className,
  rootRef,
  ...props
}: CustomComponents['Root'] extends React.ComponentType<infer P> ? P : never) {
  return (
    <div
      className={cn(className)}
      data-slot="calendar"
      ref={rootRef}
      {...props}
    />
  )
}

function CalendarWeekNumber({
  children,
  ...props
}: CustomComponents['WeekNumber'] extends React.ComponentType<infer P>
  ? P
  : never) {
  return (
    <td {...props}>
      <div className="flex size-7 items-center justify-center text-center">
        {children}
      </div>
    </td>
  )
}

export { Calendar, CalendarDayButton }
