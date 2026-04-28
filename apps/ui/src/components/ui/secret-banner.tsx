import { useState } from 'react'

import { Copy } from 'lucide-react'
import { toast } from 'sonner'

import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'

export interface SecretBannerSecret {
  copyAriaLabel?: string
  label?: string
  monospace?: boolean
  value: string
}

interface SecretBannerProps {
  description?: string
  onDismiss: () => void
  secrets: SecretBannerSecret[]
  title: string
}

export function SecretBanner({
  description,
  onDismiss,
  secrets,
  title,
}: SecretBannerProps) {
  const [copiedField, setCopiedField] = useState<null | string>(null)

  const copyToClipboard = async (text: string, id: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopiedField(id)
      setTimeout(() => setCopiedField(null), 2000)
    } catch {
      toast.error('Failed to copy to clipboard')
    }
  }

  const heading = description ? `${title} - ${description}` : title

  return (
    <div className="mb-4 rounded-lg border border-success bg-success p-4">
      <div className="mb-2 font-medium text-success">{heading}</div>
      <div className="space-y-2">
        {secrets.map((secret, index) => {
          const fieldId = `${secret.label ?? 'secret'}-${index}`
          const copyLabel =
            secret.copyAriaLabel ??
            (secret.label
              ? `Copy ${secret.label.toLowerCase()}`
              : 'Copy to clipboard')
          return (
            <div key={fieldId}>
              {secret.label && (
                <span className="text-xs text-secondary">{secret.label}</span>
              )}
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded border border-input bg-background px-3 py-2 text-sm text-success">
                  {secret.value}
                </code>
                <TooltipProvider delayDuration={200}>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <button
                        aria-label={copyLabel}
                        className={`rounded-lg p-2 ${
                          copiedField === fieldId
                            ? 'bg-green-600 text-white'
                            : 'text-secondary hover:bg-secondary'
                        }`}
                        onClick={() => copyToClipboard(secret.value, fieldId)}
                        type="button"
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                    </TooltipTrigger>
                    <TooltipContent>
                      <p>Copy to clipboard</p>
                    </TooltipContent>
                  </Tooltip>
                </TooltipProvider>
              </div>
            </div>
          )
        })}
      </div>
      <button
        className="hover:text-success/80 mt-2 text-sm text-success"
        onClick={onDismiss}
        type="button"
      >
        Dismiss
      </button>
    </div>
  )
}
