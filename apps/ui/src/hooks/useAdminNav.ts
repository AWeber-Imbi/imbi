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

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (shouldIgnoreHotkey(event)) return
      if (event.key === 'e' && viewMode === 'detail' && itemSlug) {
        event.preventDefault()
        goToEdit(itemSlug)
      } else if (
        event.key === 'Escape' &&
        (viewMode === 'edit' || viewMode === 'create')
      ) {
        event.preventDefault()
        goToList()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [viewMode, itemSlug, goToEdit, goToList])

  return {
    goToCreate,
    goToDetail,
    goToEdit,
    goToList,
    slug: itemSlug,
    viewMode,
  }
}

function hasOpenOverlay(): boolean {
  // Radix marks open dialogs, popovers, menus, etc. with data-state="open".
  // Any open overlay should swallow these hotkeys so they don't fight it.
  return document.querySelector('[data-state="open"]') !== null
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  if (target.closest('[contenteditable="true"], [contenteditable=""]'))
    return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

function shouldIgnoreHotkey(event: KeyboardEvent): boolean {
  if (event.defaultPrevented || event.repeat) return true
  if (event.ctrlKey || event.metaKey || event.altKey) return true
  if (isTypingTarget(event.target)) return true
  return hasOpenOverlay()
}
