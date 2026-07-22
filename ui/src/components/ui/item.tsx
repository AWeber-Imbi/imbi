/* eslint-disable react-refresh/only-export-components */
import * as React from 'react'

import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const itemVariants = cva(
  'group/item flex flex-wrap items-center rounded-md border border-transparent text-sm transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 [a]:hover:bg-accent/50',
  {
    defaultVariants: {
      size: 'default',
      variant: 'default',
    },
    variants: {
      size: {
        default: 'gap-4 p-4',
        sm: 'gap-2.5 px-4 py-3',
      },
      variant: {
        default: 'bg-transparent',
        muted: 'bg-muted/50',
        outline: 'border-border',
      },
    },
  },
)

interface ItemProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof itemVariants> {
  asChild?: boolean
}

const Item = React.forwardRef<HTMLDivElement, ItemProps>(
  ({ asChild = false, className, size, variant, ...props }, ref) => {
    const Comp = asChild ? Slot : 'div'
    return (
      <Comp
        className={cn(itemVariants({ size, variant }), className)}
        ref={ref}
        {...props}
      />
    )
  },
)
Item.displayName = 'Item'

const ItemGroup = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div className={cn('flex flex-col', className)} ref={ref} {...props} />
))
ItemGroup.displayName = 'ItemGroup'

const itemMediaVariants = cva(
  'flex shrink-0 items-center justify-center gap-2 [&_svg]:pointer-events-none',
  {
    defaultVariants: {
      variant: 'default',
    },
    variants: {
      variant: {
        default: 'self-center [&_svg]:size-4',
        icon: 'size-8 rounded-sm border bg-muted/50 [&_svg]:size-4',
      },
    },
  },
)

interface ItemMediaProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof itemMediaVariants> {}

const ItemMedia = React.forwardRef<HTMLDivElement, ItemMediaProps>(
  ({ className, variant, ...props }, ref) => (
    <div
      className={cn(itemMediaVariants({ variant }), className)}
      ref={ref}
      {...props}
    />
  ),
)
ItemMedia.displayName = 'ItemMedia'

const ItemContent = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    className={cn(
      'flex flex-1 flex-col gap-0.5 [&+[data-item-actions]]:ml-auto',
      className,
    )}
    ref={ref}
    {...props}
  />
))
ItemContent.displayName = 'ItemContent'

const ItemTitle = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    className={cn(
      'flex items-center gap-2 text-sm leading-none font-medium',
      className,
    )}
    ref={ref}
    {...props}
  />
))
ItemTitle.displayName = 'ItemTitle'

const ItemDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    className={cn('text-sm leading-normal text-muted-foreground', className)}
    ref={ref}
    {...props}
  />
))
ItemDescription.displayName = 'ItemDescription'

const ItemActions = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    className={cn('flex items-center gap-2', className)}
    data-item-actions=""
    ref={ref}
    {...props}
  />
))
ItemActions.displayName = 'ItemActions'

export {
  Item,
  ItemActions,
  ItemContent,
  ItemDescription,
  ItemGroup,
  ItemMedia,
  ItemTitle,
}
