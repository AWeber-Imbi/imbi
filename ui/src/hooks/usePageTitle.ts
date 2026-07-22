import { useEffect } from 'react'

export function usePageTitle(title: null | string | undefined) {
  useEffect(() => {
    if (!title) return
    const previous = document.title
    document.title = `Imbi ⸱ ${title}`
    return () => {
      document.title = previous
    }
  }, [title])
}
