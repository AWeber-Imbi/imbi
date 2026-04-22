import * as React from 'react'

// Label + input + error chrome shared by admin *Form.tsx components.
// Layout (grid-span etc.) stays with the caller; this only wraps the
// label, the input slot, optional description, and the error message.
export interface FormFieldProps {
  label: string
  required?: boolean
  error?: string
  touched?: boolean
  description?: string
  htmlFor?: string
  children: React.ReactNode
}

export function FormField({
  label,
  required,
  error,
  touched,
  description,
  htmlFor,
  children,
}: FormFieldProps) {
  return (
    <div>
      <label htmlFor={htmlFor} className="mb-1.5 block text-sm text-secondary">
        {label}
        {required && <span className="text-red-500"> *</span>}
      </label>
      {children}
      {description && (
        <p className="mt-1 text-sm text-secondary">{description}</p>
      )}
      {touched && error && <p className="mt-1 text-sm text-red-600">{error}</p>}
    </div>
  )
}
