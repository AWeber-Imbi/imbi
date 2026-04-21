import { useEffect } from 'react'

export function usePageTitle(title: string | undefined | null) {
  useEffect(() => {
    if (!title) return
    const previous = document.title
    document.title = `Imbi ⸱ ${title}`
    return () => {
      document.title = previous
    }
  }, [title])
}
