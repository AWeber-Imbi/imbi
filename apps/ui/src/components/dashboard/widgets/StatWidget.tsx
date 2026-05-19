import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

interface StatWidgetProps {
  icon: string
  isError?: boolean
  isLoading?: boolean
  onClick?: () => void
  title: string
  value: string
}

// fallow-ignore-next-line complexity
export function StatWidget({
  icon,
  isError = false,
  isLoading = false,
  onClick,
  title,
  value,
}: StatWidgetProps) {
  return (
    <Card
      className={`relative flex h-full flex-col${onClick ? ' hover:border-secondary cursor-pointer transition-colors' : ''}`}
      onClick={onClick}
      onKeyDown={
        onClick
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onClick()
              }
            }
          : undefined
      }
      role={onClick ? 'link' : undefined}
      tabIndex={onClick ? 0 : undefined}
    >
      <div className="absolute top-6 right-6 text-4xl">{icon}</div>
      <CardHeader className="pb-2">
        <CardTitle className="text-secondary font-normal">{title}</CardTitle>
      </CardHeader>
      <CardContent className="mt-auto">
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
