import { useCallback } from 'react'
import { deleteUpload } from '@/api/endpoints'

/**
 * Returns a setter that cleans up any previously uploaded file before
 * applying the new icon value. Pass the current icon value and the
 * real setter. The returned function should be handed to both
 * IconPicker's and IconUpload's `onChange`.
 */
export function useIconWithCleanup(
  currentIcon: string,
  setIcon: (v: string) => void,
) {
  return useCallback(
    (newValue: string) => {
      // If the current icon is an uploaded file and we are replacing it
      // with a different value, delete the old upload from the server.
      if (
        currentIcon &&
        currentIcon.startsWith('/uploads/') &&
        newValue !== currentIcon
      ) {
        const match = currentIcon.match(/\/uploads\/(.+)$/)
        if (match) {
          deleteUpload(match[1]).catch(() => {
            // Best-effort cleanup; ignore errors
          })
        }
      }
      setIcon(newValue)
    },
    [currentIcon, setIcon],
  )
}
