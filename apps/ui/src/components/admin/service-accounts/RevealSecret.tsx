import { useState } from 'react'

import { Check, Copy } from 'lucide-react'

import { Button } from '@/components/ui/button'

interface RevealSecretProps {
  label: string
  onCopy?: () => void
  value: string
}

interface RevealSecretRowProps {
  fieldLabel?: string
  onCopy?: () => void
  value: string
}

export function RevealSecret({ label, onCopy, value }: RevealSecretProps) {
  return (
    <div className="space-y-3 py-1">
      <p className="text-sm text-secondary">{label}</p>
      <RevealSecretRow onCopy={onCopy} value={value} />
    </div>
  )
}

export function RevealSecretRow({
  fieldLabel,
  onCopy,
  value,
}: RevealSecretRowProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard?.writeText(value)
    onCopy?.()
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="space-y-1">
      {fieldLabel && (
        <span className="text-xs font-medium text-secondary">{fieldLabel}</span>
      )}
      <div className="flex items-center gap-2">
        <code className="flex-1 break-all rounded-lg border border-input bg-secondary px-3 py-2 text-sm text-primary">
          {value}
        </code>
        <Button
          className="flex-shrink-0"
          onClick={handleCopy}
          size="sm"
          variant="outline"
        >
          {copied ? (
            <Check className="h-3.5 w-3.5 text-success" />
          ) : (
            <Copy className="h-3.5 w-3.5" />
          )}
        </Button>
      </div>
    </div>
  )
}
