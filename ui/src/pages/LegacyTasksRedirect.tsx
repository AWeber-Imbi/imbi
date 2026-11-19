import { Navigate, useLocation, useParams } from 'react-router-dom'

/**
 * An old `/agents/tasks/...` link: go to the same ticket under `/tickets`
 * (ADR 0028). App.tsx imports this module directly, not lazily, so the
 * redirect does not wait for the tickets chunk. Old bookmarks and links
 * use these URLs, so it stays.
 */
export function LegacyTasksRedirect() {
  const { action, slug, tab } = useParams()
  const { hash, search } = useLocation()
  const path = [slug, action, tab]
    .filter((p): p is string => !!p)
    .map(encodeURIComponent)
  return (
    <Navigate
      replace
      to={`${['/tickets', ...path].join('/')}${search}${hash}`}
    />
  )
}
