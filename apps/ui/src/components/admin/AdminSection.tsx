import type { ReactNode } from 'react'

import { Plus, Search } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'

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
  onCreate: () => void
  onSearchChange: (value: string) => void
  /** Controlled search value. */
  search: string
  /** Placeholder for the search input. */
  searchPlaceholder: string
}

// The search input and create button are static chrome — they render
// immediately. The loading affordance lives in the child table (pass
// `loading` to AdminTable) so the page never shows a centered label.
export function AdminSection({
  children,
  createLabel,
  error,
  errorTitle,
  headerActions,
  headerExtras,
  onCreate,
  onSearchChange,
  search,
  searchPlaceholder,
}: AdminSectionProps) {
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
                'text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2'
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
            <Plus className="mr-2 size-4" />
            {createLabel}
          </Button>
        </div>
      </div>

      {children}
    </div>
  )
}
