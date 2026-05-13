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
    <div className="border-border bg-card rounded-lg border p-6">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-secondary text-sm">{title}</p>
          {isLoading ? (
            <span
              aria-label={`Loading ${title}`}
              className="bg-tertiary/40 mt-2 inline-block h-8 w-20 animate-pulse rounded"
              role="status"
            />
          ) : isError ? (
            <p className="text-danger mt-2 text-sm">Unavailable</p>
          ) : (
            <p className="text-primary mt-2 text-3xl">{value}</p>
          )}
        </div>
        <div className="text-4xl">{icon}</div>
      </div>
    </div>
  )
}
