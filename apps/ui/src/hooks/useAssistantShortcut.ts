import { useEffect } from 'react'

export function useAssistantShortcut(
  ref: React.RefObject<HTMLInputElement | null>,
  isExpanded: boolean,
  setExpanded: (expanded: boolean) => void,
) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'A' && e.shiftKey && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        if (!isExpanded) setExpanded(true)
        ref.current?.focus()
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [isExpanded, ref, setExpanded])
}
