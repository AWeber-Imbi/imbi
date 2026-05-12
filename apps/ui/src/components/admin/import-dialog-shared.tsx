import { Upload } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { DialogFooter } from '@/components/ui/dialog'

interface ImportDialogFooterProps {
  hasInput: boolean
  isLoading: boolean
  onClose: () => void
  onImport: () => void
}

export function ImportDialogFooter({
  hasInput,
  isLoading,
  onClose,
  onImport,
}: ImportDialogFooterProps) {
  return (
    <DialogFooter>
      <Button disabled={isLoading} onClick={onClose} variant="outline">
        Cancel
      </Button>
      <Button
        className="bg-action text-action-foreground hover:bg-action-hover"
        disabled={isLoading || !hasInput}
        onClick={onImport}
      >
        <Upload className="mr-2 h-4 w-4" />
        {isLoading ? 'Importing...' : 'Import'}
      </Button>
    </DialogFooter>
  )
}
