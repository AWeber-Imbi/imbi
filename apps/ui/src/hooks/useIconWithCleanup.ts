import { useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
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
  const { mutate: mutateDeleteUpload } = useMutation({
    mutationFn: deleteUpload,
  })

  return useCallback(
    (newValue: string) => {
      // If the current icon is an uploaded file and we are replacing it
      // with a different non-empty value (e.g. switching to a Simple Icon),
      // delete the old upload from the server. Skip cleanup when newValue
      // is empty because that signals removal from IconUpload, which
      // handles its own deletion in handleRemove().
      if (
        currentIcon &&
        currentIcon.startsWith('/uploads/') &&
        newValue !== currentIcon &&
        newValue !== ''
      ) {
        const match = currentIcon.match(/\/uploads\/(.+)$/)
        if (match) {
          mutateDeleteUpload(match[1], {
            onError: () => {
              // Best-effort cleanup; ignore errors
            },
          })
        }
      }
      setIcon(newValue)
    },
    [currentIcon, setIcon, mutateDeleteUpload],
  )
}
