import { Link } from 'react-router-dom'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'

interface StatWidgetProps {
  // When set, the card renders a real link so cmd/ctrl/middle-click open a
  // new tab. Takes precedence over onClick.
  href?: string
  icon: string
  isError?: boolean
  isLoading?: boolean
  onClick?: () => void
  title: string
  value: string
}

// fallow-ignore-next-line complexity
export function StatWidget({
  href,
  icon,
  isError = false,
  isLoading = false,
  onClick,
  title,
  value,
}: StatWidgetProps) {
  const clickable = !!href || !!onClick
  return (
    <Card
      className={`relative flex h-full flex-col${clickable ? ' hover:border-secondary cursor-pointer transition-colors' : ''}`}
      onClick={href ? undefined : onClick}
      onKeyDown={
        !href && onClick
          ? (event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onClick()
              }
            }
          : undefined
      }
      role={!href && onClick ? 'link' : undefined}
      tabIndex={!href && onClick ? 0 : undefined}
    >
      {href && (
        <Link
          aria-label={title}
          className="focus-visible:ring-ring absolute inset-0 rounded-lg focus-visible:ring-2 focus-visible:outline-none"
          to={href}
        />
      )}
      <div className="absolute top-6 right-6 text-4xl">{icon}</div>
      <CardHeader className="pb-2">
        <CardTitle className="text-secondary font-normal">{title}</CardTitle>
      </CardHeader>
      <CardContent className="mt-auto">
        {isLoading ? (
          <Skeleton
            aria-label={`Loading ${title}`}
            className="bg-tertiary/40 inline-block h-8 w-20"
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
