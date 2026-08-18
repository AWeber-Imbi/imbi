import * as React from 'react'

import { cn } from '@/lib/utils'

export type TextareaProps =
  React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
    /**
     * Grow the field to fit its content instead of scrolling inside a fixed
     * height. Bound the growth with a `max-h-*` class on the caller.
     */
    autoResize?: boolean
  }

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ autoResize = false, className, onChange, ...props }, ref) => {
    const inner = React.useRef<HTMLTextAreaElement>(null)
    React.useImperativeHandle(ref, () => inner.current as HTMLTextAreaElement)

    const grow = () => {
      const el = inner.current
      if (!el || !autoResize) return
      // Collapse first so the height can shrink as well as grow; scrollHeight
      // never reports less than the current height.
      el.style.height = 'auto'
      el.style.height = `${el.scrollHeight}px`
    }

    // Covers values set programmatically, e.g. an AI-drafted release note.
    React.useLayoutEffect(grow, [autoResize, props.value])

    // Strip leading whitespace as the user types or pastes; a leading space is
    // never meaningful in our text inputs.
    const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      const stripped = e.target.value.replace(/^\s+/, '')
      if (stripped !== e.target.value) e.target.value = stripped
      grow()
      onChange?.(e)
    }
    return (
      <textarea
        className={cn(
          'flex min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
          autoResize && 'resize-none overflow-y-auto',
          className,
        )}
        onChange={handleChange}
        ref={inner}
        {...props}
      />
    )
  },
)
Textarea.displayName = 'Textarea'

export { Textarea }
