import type { ReactNode } from 'react'

import { Plus, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'

interface AdminSectionProps {
  /** List content (stats, table, etc.). */
  children: ReactNode
  /** Label for the create button, e.g. "New Team". */
  createLabel: string
  /** List query error, if any. */
  error?: unknown
  /** Error banner title, e.g. "Failed to load teams". */
  errorTitle: string
  /** Optional extra action buttons (e.g. Import) rendered before Create. */
  headerActions?: ReactNode
  /** Optional extra controls rendered in the header (filters, etc.). */
  headerExtras?: ReactNode
  /** Whether the list query is loading. */
  isLoading: boolean
  /** Loading label, e.g. "Loading teams...". */
  loadingLabel: string
  onCreate: () => void
  onSearchChange: (value: string) => void
  /** Controlled search value. */
  search: string
  /** Placeholder for the search input. */
  searchPlaceholder: string
}

export function AdminSection({
  children,
  createLabel,
  error,
  errorTitle,
  headerActions,
  headerExtras,
  isLoading,
  loadingLabel,
  onCreate,
  onSearchChange,
  search,
  searchPlaceholder,
}: AdminSectionProps) {
  if (isLoading) {
    return <LoadingState label={loadingLabel} />
  }

  if (error) {
    return <ErrorBanner error={error} title={errorTitle} />
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-1 items-center gap-3">
          <div className="relative max-w-md flex-1">
            <Search
              className={
                'absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary'
              }
            />
            <Input
              aria-label={searchPlaceholder}
              className="pl-10"
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={searchPlaceholder}
              value={search}
            />
          </div>
          {headerExtras}
        </div>
        <div className="flex items-center gap-2">
          {headerActions}
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onCreate}
          >
            <Plus className="mr-2 h-4 w-4" />
            {createLabel}
          </Button>
        </div>
      </div>

      {children}
    </div>
  )
}
