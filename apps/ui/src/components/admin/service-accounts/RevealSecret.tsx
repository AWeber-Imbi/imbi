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
      <p className="text-secondary text-sm">{label}</p>
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
        <span className="text-secondary text-xs font-medium">{fieldLabel}</span>
      )}
      <div className="flex items-center gap-2">
        <code className="border-input bg-secondary text-primary flex-1 rounded-lg border px-3 py-2 text-sm break-all">
          {value}
        </code>
        <Button
          className="shrink-0"
          onClick={handleCopy}
          size="sm"
          variant="outline"
        >
          {copied ? (
            <Check className="text-success size-3.5" />
          ) : (
            <Copy className="size-3.5" />
          )}
        </Button>
      </div>
    </div>
  )
}
