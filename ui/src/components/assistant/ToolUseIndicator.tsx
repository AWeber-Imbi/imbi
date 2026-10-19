import { Sparkles } from 'lucide-react'

import { Sk } from '@/components/ui/skeleton'

import { toolLabel } from './toolLabels'

interface ToolUseIndicatorProps {
  toolName: string
}

export function ToolUseIndicator({ toolName }: ToolUseIndicatorProps) {
  const friendlyName = toolLabel(toolName)

  return (
    <div className="flex flex-col gap-1.5 py-1 pl-4">
      <div className="text-amber-text flex items-center gap-2 font-mono text-xs">
        <Sparkles className="size-3" />
        <span>{friendlyName}…</span>
      </div>
      <Sk ai line w="60%" />
    </div>
  )
}
