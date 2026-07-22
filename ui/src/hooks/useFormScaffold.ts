import { useCallback, useState } from 'react'

// Shared validation/touched state used by admin *Form.tsx components.
// Consumers own their validator functions and call setValidationErrors /
// setTouched directly; this hook just removes the duplicated state + the
// handleFieldChange helper that marks a field touched and clears its error.
export interface FormScaffold {
  handleFieldChange: (field: string) => void
  setTouched: React.Dispatch<React.SetStateAction<Record<string, boolean>>>
  setValidationErrors: React.Dispatch<
    React.SetStateAction<Record<string, string>>
  >
  touched: Record<string, boolean>
  validationErrors: Record<string, string>
}

export function useFormScaffold(): FormScaffold {
  const [validationErrors, setValidationErrors] = useState<
    Record<string, string>
  >({})
  const [touched, setTouched] = useState<Record<string, boolean>>({})

  const handleFieldChange = useCallback((field: string) => {
    setTouched((prev) => ({ ...prev, [field]: true }))
    setValidationErrors((prev) => {
      if (!prev[field]) return prev
      const next = { ...prev }
      delete next[field]
      return next
    })
  }, [])

  return {
    handleFieldChange,
    setTouched,
    setValidationErrors,
    touched,
    validationErrors,
  }
}
