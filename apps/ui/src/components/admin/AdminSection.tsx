import type { ReactNode } from 'react'
import { Plus, Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import { ErrorBanner } from '@/components/ui/error-banner'

interface AdminSectionProps {
  /** Placeholder for the search input. */
  searchPlaceholder: string
  /** Controlled search value. */
  search: string
  onSearchChange: (value: string) => void
  /** Label for the create button, e.g. "New Team". */
  createLabel: string
  onCreate: () => void
  /** Whether the list query is loading. */
  isLoading: boolean
  /** Loading label, e.g. "Loading teams...". */
  loadingLabel: string
  /** List query error, if any. */
  error?: unknown
  /** Error banner title, e.g. "Failed to load teams". */
  errorTitle: string
  /** Optional extra controls rendered in the header (filters, etc.). */
  headerExtras?: ReactNode
  /** Optional extra action buttons (e.g. Import) rendered before Create. */
  headerActions?: ReactNode
  /** List content (stats, table, etc.). */
  children: ReactNode
}

export function AdminSection({
  searchPlaceholder,
  search,
  onSearchChange,
  createLabel,
  onCreate,
  isLoading,
  loadingLabel,
  error,
  errorTitle,
  headerExtras,
  headerActions,
  children,
}: AdminSectionProps) {
  if (isLoading) {
    return <LoadingState label={loadingLabel} />
  }

  if (error) {
    return <ErrorBanner title={errorTitle} error={error} />
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
              placeholder={searchPlaceholder}
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              className="pl-10"
            />
          </div>
          {headerExtras}
        </div>
        <div className="flex items-center gap-2">
          {headerActions}
          <Button
            onClick={onCreate}
            className="bg-action text-action-foreground hover:bg-action-hover"
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
