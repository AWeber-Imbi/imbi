'use client'

import * as React from 'react'

import * as ToggleGroupPrimitive from '@radix-ui/react-toggle-group'
import { type VariantProps } from 'class-variance-authority'

import { toggleVariants } from '@/components/ui/toggle'
import { cn } from '@/lib/utils'

const ToggleGroupContext = React.createContext<
  VariantProps<typeof toggleVariants> & {
    orientation?: 'horizontal' | 'vertical'
    spacing?: number
  }
>({
  orientation: 'horizontal',
  size: 'default',
  spacing: 2,
  variant: 'default',
})

function ToggleGroup({
  children,
  className,
  orientation = 'horizontal',
  size,
  spacing = 2,
  variant,
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Root> &
  VariantProps<typeof toggleVariants> & {
    orientation?: 'horizontal' | 'vertical'
    spacing?: number
  }) {
  return (
    <ToggleGroupPrimitive.Root
      className={cn(
        // oxlint-disable-next-line css-vars/no-unknown-css-var
        'group/toggle-group flex w-fit flex-row items-center gap-[--spacing(var(--gap))] rounded-lg data-[size=sm]:rounded-[min(var(--radius-md),10px)] data-vertical:flex-col data-vertical:items-stretch',
        className,
      )}
      data-orientation={orientation}
      data-size={size}
      data-slot="toggle-group"
      data-spacing={spacing}
      data-variant={variant}
      style={{ '--gap': spacing } as React.CSSProperties}
      {...props}
    >
      <ToggleGroupContext.Provider
        value={{ orientation, size, spacing, variant }}
      >
        {children}
      </ToggleGroupContext.Provider>
    </ToggleGroupPrimitive.Root>
  )
}

function ToggleGroupItem({
  children,
  className,
  size = 'default',
  variant = 'default',
  ...props
}: React.ComponentProps<typeof ToggleGroupPrimitive.Item> &
  VariantProps<typeof toggleVariants>) {
  const context = React.useContext(ToggleGroupContext)

  return (
    <ToggleGroupPrimitive.Item
      className={cn(
        'shrink-0 group-data-[spacing=0]/toggle-group:rounded-none group-data-[spacing=0]/toggle-group:px-2 focus:z-10 focus-visible:z-10 group-data-[spacing=0]/toggle-group:has-data-[icon=inline-end]:pr-1.5 group-data-[spacing=0]/toggle-group:has-data-[icon=inline-start]:pl-1.5 first:group-data-horizontal/toggle-group:data-[spacing=0]:rounded-l-lg first:group-data-vertical/toggle-group:data-[spacing=0]:rounded-t-lg last:group-data-horizontal/toggle-group:data-[spacing=0]:rounded-r-lg last:group-data-vertical/toggle-group:data-[spacing=0]:rounded-b-lg group-data-horizontal/toggle-group:data-[spacing=0]:data-[variant=outline]:border-l-0 group-data-vertical/toggle-group:data-[spacing=0]:data-[variant=outline]:border-t-0 first:group-data-horizontal/toggle-group:data-[spacing=0]:data-[variant=outline]:border-l first:group-data-vertical/toggle-group:data-[spacing=0]:data-[variant=outline]:border-t',
        toggleVariants({
          size: context.size || size,
          variant: context.variant || variant,
        }),
        className,
      )}
      data-size={context.size || size}
      data-slot="toggle-group-item"
      data-spacing={context.spacing}
      data-variant={context.variant || variant}
      {...props}
    >
      {children}
    </ToggleGroupPrimitive.Item>
  )
}

export { ToggleGroup, ToggleGroupItem }
