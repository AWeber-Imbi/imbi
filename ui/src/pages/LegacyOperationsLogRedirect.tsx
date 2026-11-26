import { Navigate, useLocation } from 'react-router-dom'

/**
 * An old `/operations-log` (or `/opslog`) link: go to the Operations Log
 * report and keep the query string, so `?entry=<id>` still highlights
 * the entry.
 */
export function LegacyOperationsLogRedirect() {
  const { hash, search } = useLocation()
  return <Navigate replace to={`/reports/operations-log${search}${hash}`} />
}
