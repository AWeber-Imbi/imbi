import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

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
    <Card className="h-full">
      <CardHeader className="flex-row items-start justify-between space-y-0 pb-2">
        <CardTitle className="text-secondary font-normal">{title}</CardTitle>
        <div className="text-4xl">{icon}</div>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <span
            aria-label={`Loading ${title}`}
            className="bg-tertiary/40 inline-block h-8 w-20 animate-pulse rounded"
            role="status"
          />
        ) : isError ? (
          <p className="text-danger text-sm">Unavailable</p>
        ) : (
          <p className="text-primary text-3xl">{value}</p>
        )}
      </CardContent>
    </Card>
  )
}
