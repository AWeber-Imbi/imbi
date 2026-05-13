import { Check } from 'lucide-react'

import { cn } from '@/lib/utils'

interface SavedIndicatorProps {
  className?: string
  show: boolean
}

export function SavedIndicator({ className, show }: SavedIndicatorProps) {
  return (
    <Check
      aria-hidden
      className={cn(
        'pointer-events-none absolute top-1/2 right-2 size-4 -translate-y-1/2 text-green-600 transition-opacity duration-500',
        show ? 'opacity-100' : 'opacity-0',
        className,
      )}
    />
  )
}
