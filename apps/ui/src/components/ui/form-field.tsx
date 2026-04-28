import * as React from 'react'

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
  return (
    <div>
      <label className="mb-1.5 block text-sm text-secondary" htmlFor={htmlFor}>
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
