import { useEffect } from 'react'

export function useSearchShortcut(
  ref: React.RefObject<HTMLInputElement | null>,
) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key !== '/') return
      const target = e.target as HTMLElement
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      )
        return
      if (ref.current?.disabled) return
      e.preventDefault()
      ref.current?.focus()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [ref])
}
