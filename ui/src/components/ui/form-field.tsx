import * as React from 'react'

import { Label } from '@/components/ui/label'

// Label + input + error chrome shared by admin *Form.tsx components.
// Layout (grid-span etc.) stays with the caller; this only wraps the
// label, the input slot, optional description, and the error message.
export interface FormFieldProps {
  children: React.ReactNode
  description?: string
  error?: string
  htmlFor?: string
  label: string
  required?: boolean
  touched?: boolean
}

export function FormField({
  children,
  description,
  error,
  htmlFor,
  label,
  required,
  touched,
}: FormFieldProps) {
  const shown = touched && error
  const fallbackId = React.useId()
  // Link the input to its error, so a screen reader announces both.
  const errorId = shown ? `${htmlFor ?? fallbackId}-error` : undefined
  const field =
    errorId && React.isValidElement<Record<string, unknown>>(children)
      ? React.cloneElement(children, {
          'aria-describedby': errorId,
          'aria-invalid': true,
        })
      : children
  return (
    <div>
      <Label className="text-secondary mb-1.5 block text-sm" htmlFor={htmlFor}>
        {label}
        {required && <span className="text-red-500"> *</span>}
      </Label>
      {field}
      {description && (
        <p className="text-secondary mt-1 text-sm">{description}</p>
      )}
      {shown && (
        <p className="mt-1 text-sm text-red-600" id={errorId}>
          {error}
        </p>
      )}
    </div>
  )
}
