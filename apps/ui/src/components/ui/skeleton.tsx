import type { HTMLAttributes } from 'react'

import { cn } from '@/lib/utils'

/**
 * Loading placeholder block. Apply size/shape via className (h-*, w-*,
 * rounded-*). The default surface tone (`bg-tertiary/30`) matches the
 * other skeleton patterns already in the codebase.
 */
export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('animate-pulse rounded bg-tertiary/30', className)}
      {...props}
    />
  )
}
