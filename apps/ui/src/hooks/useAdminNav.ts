import { useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'

export type ViewMode = 'list' | 'create' | 'edit' | 'detail'

interface AdminNavState {
  viewMode: ViewMode
  slug: string | null
  goToList: () => void
  goToCreate: () => void
  goToDetail: (slug: string) => void
  goToEdit: (slug: string) => void
}

export function useAdminNav(): AdminNavState {
  const { section, slug, action } = useParams<{
    section?: string
    slug?: string
    action?: string
  }>()
  const navigate = useNavigate()

  let viewMode: ViewMode = 'list'
  let itemSlug: string | null = null

  if (slug === 'new') {
    viewMode = 'create'
  } else if (slug) {
    itemSlug = slug
    viewMode = action === 'edit' ? 'edit' : 'detail'
  }

  const base = `/admin/${section}`

  const goToList = useCallback(
    () => navigate(base),
    [navigate, base],
  )

  const goToCreate = useCallback(
    () => navigate(`${base}/new`),
    [navigate, base],
  )

  const goToDetail = useCallback(
    (s: string) => navigate(`${base}/${encodeURIComponent(s)}`),
    [navigate, base],
  )

  const goToEdit = useCallback(
    (s: string) =>
      navigate(`${base}/${encodeURIComponent(s)}/edit`),
    [navigate, base],
  )

  return {
    viewMode,
    slug: itemSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  }
}
