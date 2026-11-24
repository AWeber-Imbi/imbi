import * as React from 'react'

import { cva, type VariantProps } from 'class-variance-authority'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'

function InputGroup({ className, ...props }: React.ComponentProps<'div'>) {
  return (
    <div
      className={cn(
        'group/input-group relative flex h-8 w-full min-w-0 items-center rounded-md border border-input bg-background transition-colors outline-none has-disabled:opacity-50 has-[[data-slot=input-group-control]:focus-visible]:border-ring has-[[data-slot=input-group-control]:focus-visible]:ring-3 has-[[data-slot=input-group-control]:focus-visible]:ring-ring/50 has-[[data-slot][aria-invalid=true]]:border-destructive has-[[data-slot][aria-invalid=true]]:ring-3 has-[[data-slot][aria-invalid=true]]:ring-destructive/20 has-[>[data-align=inline-end]]:[&>input]:pr-1.5 has-[>[data-align=inline-start]]:[&>input]:pl-1.5',
        className,
      )}
      data-slot="input-group"
      role="group"
      {...props}
    />
  )
}

const inputGroupAddonVariants = cva(
  "flex h-auto cursor-text items-center justify-center gap-2 py-1.5 text-sm font-medium text-muted-foreground select-none group-data-[disabled=true]/input-group:opacity-50 [&>svg:not([class*='size-'])]:size-4",
  {
    defaultVariants: {
      align: 'inline-start',
    },
    variants: {
      align: {
        'inline-end': 'order-last pr-2 has-[>button]:mr-[-0.3rem]',
        'inline-start': 'order-first pl-2 has-[>button]:ml-[-0.3rem]',
      },
    },
  },
)

function InputGroupAddon({
  align = 'inline-start',
  className,
  ...props
}: React.ComponentProps<'div'> & VariantProps<typeof inputGroupAddonVariants>) {
  return (
    <div
      className={cn(inputGroupAddonVariants({ align }), className)}
      data-align={align}
      data-slot="input-group-addon"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest('button')) return
        e.currentTarget.parentElement?.querySelector('input')?.focus()
      }}
      role="group"
      {...props}
    />
  )
}

const inputGroupButtonVariants = cva(
  'flex items-center gap-2 text-sm shadow-none',
  {
    defaultVariants: {
      size: 'icon-xs',
    },
    variants: {
      size: {
        'icon-xs': 'size-6 rounded-sm p-0 has-[>svg]:p-0 [&_svg]:size-3.5',
      },
    },
  },
)

function InputGroupButton({
  className,
  size = 'icon-xs',
  type = 'button',
  variant = 'ghost',
  ...props
}: Omit<React.ComponentProps<typeof Button>, 'size'> &
  VariantProps<typeof inputGroupButtonVariants>) {
  return (
    <Button
      className={cn(inputGroupButtonVariants({ size }), className)}
      data-size={size}
      type={type}
      variant={variant}
      {...props}
    />
  )
}

function InputGroupInput({
  className,
  ...props
}: React.ComponentProps<'input'>) {
  return (
    <Input
      className={cn(
        'h-full flex-1 rounded-none border-0 bg-transparent px-2.5 py-0 shadow-none ring-0 focus-visible:ring-0 focus-visible:ring-offset-0 disabled:bg-transparent aria-invalid:ring-0',
        className,
      )}
      data-slot="input-group-control"
      {...props}
    />
  )
}

export { InputGroup, InputGroupAddon, InputGroupButton, InputGroupInput }
