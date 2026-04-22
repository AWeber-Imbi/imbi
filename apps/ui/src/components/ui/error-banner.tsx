import { AlertCircle } from 'lucide-react'
import { extractApiErrorDetail } from '@/lib/apiError'

interface ErrorBannerProps {
  title: string
  message?: string
  error?: unknown
}

export function ErrorBanner({ title, message, error }: ErrorBannerProps) {
  const resolvedMessage =
    message ?? extractApiErrorDetail(error, 'An error occurred')
  return (
    <div
      role="alert"
      aria-live="assertive"
      aria-atomic="true"
      className={
        'flex items-center gap-3 rounded-lg border border-danger bg-danger p-4 text-danger'
      }
    >
      <AlertCircle className="h-5 w-5 flex-shrink-0" />
      <div>
        <div className="font-medium">{title}</div>
        <div className="mt-1 text-sm">{resolvedMessage}</div>
      </div>
    </div>
  )
}
