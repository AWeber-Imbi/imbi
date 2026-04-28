/* eslint-disable react-refresh/only-export-components */
import * as React from 'react'

import { cva, type VariantProps } from 'class-variance-authority'

import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded px-2 py-0.5 text-xs font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
  {
    defaultVariants: {
      variant: 'default',
    },
    variants: {
      variant: {
        accent: 'border border-transparent bg-accent text-accent',
        danger: 'border border-transparent bg-danger text-danger',
        default:
          'border border-transparent bg-action text-action-foreground hover:bg-action-hover',
        destructive:
          'border border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80',
        info: 'border border-transparent bg-info text-info',
        neutral: 'border border-transparent bg-tertiary text-secondary',
        outline: 'border border-secondary text-primary',
        secondary:
          'border border-transparent bg-secondary text-primary hover:bg-secondary/80',
        success: 'border border-transparent bg-success text-success',
        warning: 'border border-transparent bg-warning text-warning',
      },
    },
  },
)

export interface BadgeProps
  extends
    React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  )
}

export { Badge, badgeVariants }
