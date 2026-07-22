import { useState } from 'react'

import { Play, RefreshCw } from 'lucide-react'

import type { MaintenanceOperation } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Sk } from '@/components/ui/skeleton'
import { useMaintenanceOperations } from '@/hooks/useMaintenanceOperations'
import { extractApiErrorDetail } from '@/lib/apiError'
import { formatRelativeDate } from '@/lib/formatDate'

// Global maintenance page: renders whatever operations the backend
// registry returns — no slugs are hardcoded here, so new operations
// appear without UI changes.
export function MaintenanceManagement() {
  const {
    cancel,
    cancelingSlugs,
    error,
    isError,
    isLoading,
    operations,
    run,
    runningSlugs,
  } = useMaintenanceOperations()
  const [confirming, setConfirming] = useState<MaintenanceOperation | null>(
    null,
  )

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-primary text-2xl font-semibold tracking-tight">
          Maintenance
        </h1>
        <p className="text-secondary mt-1 text-sm">
          Global background operations — each run applies to every project
          across all organizations.
        </p>
      </div>

      {isError ? (
        <Card>
          <CardContent className="text-destructive py-8 text-center text-sm">
            {extractApiErrorDetail(error) ??
              'Failed to load maintenance operations'}
          </CardContent>
        </Card>
      ) : (
        <Card>
          <CardContent className="divide-border/50 divide-y p-0">
            {isLoading ? (
              Array.from({ length: 4 }).map((_, i) => (
                <div
                  className="flex items-center justify-between px-4 py-3"
                  key={`sk-${i}`}
                >
                  <div className="min-w-0 flex-1 space-y-2">
                    <Sk line w="30%" />
                    <Sk line w="55%" />
                  </div>
                  <Sk h={32} w={72} />
                </div>
              ))
            ) : operations.length === 0 ? (
              <div className="text-muted-foreground py-12 text-center text-sm">
                No maintenance operations are available.
              </div>
            ) : (
              operations.map((op) => (
                <OperationRow
                  canceling={cancelingSlugs.has(op.slug)}
                  key={op.slug}
                  onCancel={() => cancel(op.slug)}
                  onRun={() => setConfirming(op)}
                  op={op}
                  starting={runningSlugs.has(op.slug)}
                />
              ))
            )}
          </CardContent>
        </Card>
      )}

      <ConfirmDialog
        confirmLabel="Run"
        description={
          confirming
            ? `"${confirming.label}" runs across every project in all organizations. This may take a while and generate significant load.`
            : ''
        }
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming) run(confirming.slug)
          setConfirming(null)
        }}
        open={confirming !== null}
        title={confirming ? `Run ${confirming.label}?` : ''}
      />
    </div>
  )
}

function OperationRow({
  canceling,
  onCancel,
  onRun,
  op,
  starting,
}: {
  canceling: boolean
  onCancel: () => void
  onRun: () => void
  op: MaintenanceOperation
  starting: boolean
}) {
  const running = op.state === 'running'
  return (
    <div className="flex items-center gap-4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="text-primary text-sm font-medium">{op.label}</div>
        {op.description && (
          <div className="text-secondary mt-0.5 text-xs">{op.description}</div>
        )}
      </div>
      <OperationStatus op={op} />
      <div className="flex shrink-0 items-center gap-2">
        {running && (
          <Button
            disabled={canceling}
            onClick={onCancel}
            size="sm"
            variant="ghost"
          >
            Cancel
          </Button>
        )}
        <Button
          disabled={running || starting}
          onClick={onRun}
          size="sm"
          variant="outline"
        >
          <Play className="size-3.5" />
          Run
        </Button>
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function OperationStatus({ op }: { op: MaintenanceOperation }) {
  const progress = op.progress
  if (op.state === 'running') {
    const total = progress?.total ?? null
    const remaining = progress?.remaining ?? null
    const failed = progress?.failed ?? 0
    const done = total != null && remaining != null ? total - remaining : null
    return (
      <div className="shrink-0 text-right">
        <div className="text-amber-text flex items-center justify-end gap-2 text-xs">
          <RefreshCw className="size-3.5 animate-spin" />
          <span>
            {done != null && total != null
              ? `${done} of ${total} — ${remaining} remaining`
              : 'Running'}
          </span>
          {failed > 0 && (
            <span className="text-destructive">{failed} failed</span>
          )}
        </div>
        <div className="text-tertiary mt-0.5 text-xs">
          Started {formatRelativeDate(op.started_at)}
          {op.started_by ? ` by ${op.started_by}` : ''}
        </div>
      </div>
    )
  }
  if (
    op.state === 'completed' ||
    op.state === 'cancelled' ||
    op.state === 'abandoned'
  ) {
    return (
      <div className="shrink-0 text-right">
        <div className="text-tertiary text-xs">
          Last run {op.state}
          {op.completed_at ? ` ${formatRelativeDate(op.completed_at)}` : ''}
        </div>
        {progress && (
          <div className="text-tertiary mt-0.5 text-xs">
            {progress.succeeded ?? 0} succeeded
            {(progress.skipped ?? 0) > 0 && `, ${progress.skipped} skipped`}
            {(progress.failed ?? 0) > 0 && (
              <span className="text-destructive">
                {`, ${progress.failed} failed`}
              </span>
            )}
          </div>
        )}
      </div>
    )
  }
  return null
}
