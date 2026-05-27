import * as React from 'react'

import { cn } from '@/lib/utils'

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, onChange, ...props }, ref) => {
    // Strip leading whitespace as the user types or pastes; a leading space is
    // never meaningful in our text inputs.
    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const stripped = e.target.value.replace(/^\s+/, '')
      if (stripped !== e.target.value) e.target.value = stripped
      onChange?.(e)
    }
    return (
      <textarea
        className={cn(
          'flex min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        onChange={handleChange}
        ref={ref}
        {...props}
      />
    )
  },
)
Textarea.displayName = 'Textarea'

export { Textarea }
