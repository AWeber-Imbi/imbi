import * as React from 'react'
import { Save, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

// Header row shared by admin *Form.tsx components. Admin-scoped because the
// save-button text flip (Save Changes vs Create X) is admin-specific.
export interface FormHeaderProps {
  title: string
  subtitle?: React.ReactNode
  isEditing: boolean
  isLoading: boolean
  onCancel: () => void
  onSave: () => void
  createLabel: string
}

export function FormHeader({
  title,
  subtitle,
  isEditing,
  isLoading,
  onCancel,
  onSave,
  createLabel,
}: FormHeaderProps) {
  return (
    <div className="flex items-center justify-between">
      <div>
        <h2 className="text-base font-medium text-primary">{title}</h2>
        {subtitle && <p className="mt-1 text-secondary">{subtitle}</p>}
      </div>
      <div className="flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={onCancel}
          disabled={isLoading}
        >
          <X className="mr-2 h-4 w-4" />
          Cancel
        </Button>
        <Button
          type="button"
          onClick={onSave}
          disabled={isLoading}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Save className="mr-2 h-4 w-4" />
          {isLoading ? 'Saving...' : isEditing ? 'Save Changes' : createLabel}
        </Button>
      </div>
    </div>
  )
}
