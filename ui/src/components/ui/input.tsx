import * as React from 'react'

import { cn } from '@/lib/utils'

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, onChange, type, ...props }, ref) => {
    // Strip leading whitespace as the user types or pastes. A leading space is
    // never meaningful in our text inputs, but it can be a valid password
    // character, so passwords are left untouched.
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      if (type !== 'password') {
        const stripped = e.target.value.replace(/^\s+/, '')
        if (stripped !== e.target.value) e.target.value = stripped
      }
      onChange?.(e)
    }
    return (
      <input
        className={cn(
          'flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-foreground placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
          className,
        )}
        onChange={handleChange}
        ref={ref}
        type={type}
        {...props}
      />
    )
  },
)
Input.displayName = 'Input'

export { Input }
