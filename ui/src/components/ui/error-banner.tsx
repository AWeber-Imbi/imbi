import { AlertCircle } from 'lucide-react'

import { extractApiErrorDetail } from '@/lib/apiError'

interface ErrorBannerProps {
  error?: unknown
  message?: string
  title: string
}

export function ErrorBanner({ error, message, title }: ErrorBannerProps) {
  const resolvedMessage =
    message ?? extractApiErrorDetail(error, 'An error occurred')
  return (
    <div
      aria-atomic="true"
      aria-live="assertive"
      className={
        'border-danger bg-danger text-danger flex items-center gap-3 rounded-lg border p-4'
      }
      role="alert"
    >
      <AlertCircle className="size-5 shrink-0" />
      <div>
        <div className="font-medium">{title}</div>
        <div className="mt-1 text-sm">{resolvedMessage}</div>
      </div>
    </div>
  )
}
