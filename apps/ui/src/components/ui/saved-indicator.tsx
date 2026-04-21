import { Check } from 'lucide-react'
import { cn } from '@/lib/utils'

interface SavedIndicatorProps {
  show: boolean
  className?: string
}

export function SavedIndicator({ show, className }: SavedIndicatorProps) {
  return (
    <Check
      aria-hidden
      className={cn(
        'pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-green-600 transition-opacity duration-500',
        show ? 'opacity-100' : 'opacity-0',
        className,
      )}
    />
  )
}
