import { useCallback, useEffect } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

export type ViewMode = 'create' | 'detail' | 'edit' | 'list'

interface AdminNavState {
  goToCreate: () => void
  goToDetail: (slug: string) => void
  goToEdit: (slug: string) => void
  goToList: () => void
  slug: null | string
  viewMode: ViewMode
}

export function useAdminNav(): AdminNavState {
  const { action, section, slug } = useParams<{
    action?: string
    section?: string
    slug?: string
  }>()
  const navigate = useNavigate()

  let viewMode: ViewMode = 'list'
  let itemSlug: null | string = null

  if (slug === 'new') {
    viewMode = 'create'
  } else if (slug) {
    itemSlug = slug
    viewMode = action === 'edit' ? 'edit' : 'detail'
  }

  const base = section ? `/admin/${section}` : '/admin'

  const goToList = useCallback(() => navigate(base), [navigate, base])

  const goToCreate = useCallback(
    () => navigate(`${base}/new`),
    [navigate, base],
  )

  const goToDetail = useCallback(
    (s: string) => navigate(`${base}/${encodeURIComponent(s)}`),
    [navigate, base],
  )

  const goToEdit = useCallback(
    (s: string) => navigate(`${base}/${encodeURIComponent(s)}/edit`),
    [navigate, base],
  )

  useEffect(() => {
    if (viewMode === 'edit' || viewMode === 'create') {
      window.scrollTo({ behavior: 'instant', top: 0 })
    }
  }, [viewMode])

  return {
    goToCreate,
    goToDetail,
    goToEdit,
    goToList,
    slug: itemSlug,
    viewMode,
  }
}
