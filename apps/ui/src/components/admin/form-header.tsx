import * as React from 'react'

import { Save, X } from 'lucide-react'

import { Button } from '@/components/ui/button'

// Header row shared by admin *Form.tsx components. Admin-scoped because the
// save-button text flip (Save Changes vs Create X) is admin-specific.
export interface FormHeaderProps {
  createLabel: string
  isEditing: boolean
  isLoading: boolean
  onCancel: () => void
  onSave: () => void
  subtitle?: React.ReactNode
  title: string
}

export function FormHeader({
  createLabel,
  isEditing,
  isLoading,
  onCancel,
  onSave,
  subtitle,
  title,
}: FormHeaderProps) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h2 className="text-primary text-base font-medium">{title}</h2>
        {subtitle && <p className="text-secondary mt-1">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">
        <Button
          disabled={isLoading}
          onClick={onCancel}
          type="button"
          variant="outline"
        >
          <X className="mr-2 size-4" />
          Cancel
        </Button>
        <Button
          className="bg-action text-action-foreground hover:bg-action-hover"
          disabled={isLoading}
          onClick={onSave}
          type="button"
        >
          <Save className="mr-2 size-4" />
          {isLoading ? 'Saving...' : isEditing ? 'Save Changes' : createLabel}
        </Button>
      </div>
    </div>
  )
}
