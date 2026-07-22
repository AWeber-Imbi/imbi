import { useState } from 'react'

import { CheckCircle2, Loader2, Plug, PlugZap, XCircle } from 'lucide-react'

import { ApiError } from '@/api/client'
import { Button } from '@/components/ui/button'
import { formatRelativeDate } from '@/lib/formatDate'
import { cn } from '@/lib/utils'
import type { MCPServer, MCPServerTestResult } from '@/types'

interface ConnectionTestPanelProps {
  // Called with each successful result, so the form can surface the
  // discovered tool names (e.g. in the ignored-tools picker).
  onResult?: (result: MCPServerTestResult) => void
  // Runs the test and resolves with the result. Throws on transport error.
  onTest: () => Promise<MCPServerTestResult>
  // The saved server, when editing — used to show the last-tested result
  // before the user runs a fresh test. Null on the create form.
  server: MCPServer | null
}

type Phase =
  | { kind: 'error'; message: string }
  | { kind: 'idle' }
  | { kind: 'result'; result: MCPServerTestResult }
  | { kind: 'testing' }

type Tone = 'danger' | 'neutral' | 'success'

export function ConnectionTestPanel({
  onResult,
  onTest,
  server,
}: ConnectionTestPanelProps) {
  const [phase, setPhase] = useState<Phase>({ kind: 'idle' })

  const run = async () => {
    setPhase({ kind: 'testing' })
    try {
      const result = await onTest()
      setPhase({ kind: 'result', result })
      onResult?.(result)
    } catch (err) {
      const message =
        err instanceof ApiError
          ? ((err.data as undefined | { detail?: string })?.detail ??
            err.message)
          : err instanceof Error
            ? err.message
            : 'Connection test failed'
      setPhase({ kind: 'error', message })
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-secondary text-sm">
          Verify the endpoint responds, authenticates, and lists its tools.
        </p>
        <Button
          disabled={phase.kind === 'testing'}
          onClick={run}
          size="sm"
          type="button"
          variant="outline"
        >
          {phase.kind === 'testing' ? (
            <Loader2 className="mr-2 size-4 animate-spin" />
          ) : (
            <PlugZap className="mr-2 size-4" />
          )}
          {phase.kind === 'testing' ? 'Testing…' : 'Test connection'}
        </Button>
      </div>
      <Result phase={phase} server={server} />
    </div>
  )
}

const TONE_CLASSES: Record<
  Tone,
  { container: string; icon: string; title: string }
> = {
  danger: {
    container: 'border-danger/40 bg-danger',
    icon: 'text-danger',
    title: 'text-danger',
  },
  neutral: {
    container: 'border-tertiary bg-secondary',
    icon: 'bg-primary text-tertiary',
    title: 'text-primary',
  },
  success: {
    container: 'border-success/40 bg-success',
    icon: 'text-success',
    title: 'text-success',
  },
}

function Panel({
  icon,
  sub,
  title,
  tone = 'neutral',
}: {
  icon: React.ReactNode
  sub: string
  title: string
  tone?: Tone
}) {
  const classes = TONE_CLASSES[tone]
  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-md border px-4 py-3',
        classes.container,
      )}
    >
      <span
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-full',
          classes.icon,
        )}
      >
        {icon}
      </span>
      <div className="min-w-0">
        <div className={cn('text-sm font-medium', classes.title)}>{title}</div>
        <div className="text-tertiary truncate text-xs">{sub}</div>
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function Result({ phase, server }: { phase: Phase; server: MCPServer | null }) {
  if (phase.kind === 'testing') {
    return (
      <Panel
        icon={<Loader2 className="size-4 animate-spin" />}
        sub="Hitting endpoint, negotiating tools."
        title="Testing connection…"
      />
    )
  }
  if (phase.kind === 'error') {
    return (
      <Panel
        icon={<XCircle className="size-4" />}
        sub={phase.message}
        title="Connection test failed"
        tone="danger"
      />
    )
  }
  if (phase.kind === 'result') {
    const { result } = phase
    if (!result.ok) {
      return (
        <Panel
          icon={<XCircle className="size-4" />}
          sub={`${result.error ?? 'Unreachable'} · ${result.latency_ms}ms`}
          title="Connection failed"
          tone="danger"
        />
      )
    }
    return (
      <Panel
        icon={<CheckCircle2 className="size-4" />}
        sub={`${result.latency_ms}ms · ${result.tools_discovered} tools discovered · just now`}
        title="Connection OK"
        tone="success"
      />
    )
  }
  // Idle: show the last persisted test for a saved server, else a hint.
  if (server?.last_tested_at) {
    const parts = [`${server.last_tested_latency_ms ?? '—'}ms`]
    if (server.tools_discovered != null) {
      parts.push(`${server.tools_discovered} tools discovered`)
    }
    return (
      <Panel
        icon={<CheckCircle2 className="size-4" />}
        sub={parts.join(' · ')}
        title={`Last tested ${formatRelativeDate(server.last_tested_at)}`}
      />
    )
  }
  return (
    <Panel
      icon={<Plug className="size-4" />}
      sub="Run a test to verify the endpoint responds and list its tools."
      title="Not yet tested"
    />
  )
}
