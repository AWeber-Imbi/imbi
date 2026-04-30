interface StatWidgetProps {
  icon: string
  isError?: boolean
  isLoading?: boolean
  title: string
  value: string
}

export function StatWidget({
  icon,
  isError = false,
  isLoading = false,
  title,
  value,
}: StatWidgetProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-secondary">{title}</p>
          {isLoading ? (
            <span
              aria-label={`Loading ${title}`}
              className="bg-tertiary/40 mt-2 inline-block h-8 w-20 animate-pulse rounded"
              role="status"
            />
          ) : isError ? (
            <p className="mt-2 text-sm text-danger">Unavailable</p>
          ) : (
            <p className="mt-2 text-3xl text-primary">{value}</p>
          )}
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  )
}
