import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'

import {
  fetchConfigurationHistory,
  restoreConfigurationVersion,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Sk } from '@/components/ui/skeleton'
import { extractApiErrorDetail } from '@/lib/apiError'
import { parseServerTs } from '@/lib/formatDate'
import { maskSecret } from '@/lib/maskSecret'
import type { ConfigVersionResponse } from '@/types'

interface ConfigHistoryDialogProps {
  environment: { name: string; slug: string }
  onClose: () => void
  orgSlug: string
  paramKey: string
  projectId: string
  source?: string
}

export function ConfigHistoryDialog({
  environment,
  onClose,
  orgSlug,
  paramKey,
  projectId,
  source,
}: ConfigHistoryDialogProps) {
  const queryClient = useQueryClient()
  const [revealed, setRevealed] = useState<Record<string, boolean>>({})
  const [pending, setPending] = useState<null | string>(null)
  const params = { environment: environment.slug, source }
  const queryKey = [
    'config-history',
    orgSlug,
    projectId,
    source,
    environment.slug,
    paramKey,
  ]

  const { data, error, isLoading } = useQuery({
    queryFn: () =>
      fetchConfigurationHistory(orgSlug, projectId, paramKey, params),
    queryKey,
  })

  const restore = useMutation({
    mutationFn: (version: string) =>
      restoreConfigurationVersion(
        orgSlug,
        projectId,
        paramKey,
        version,
        params,
      ),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to restore version')
    },
    onSuccess: (_, version) => {
      toast.success(`Restored version ${version} in ${environment.name}`)
      setPending(null)
      void Promise.all(
        ['config-keys', 'config-values', 'config-history'].map((name) =>
          queryClient.invalidateQueries({
            queryKey: [name, orgSlug, projectId, source, environment.slug],
          }),
        ),
      )
    },
  })

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>History</DialogTitle>
          <DialogDescription>
            <span className="font-mono">{paramKey}</span> in {environment.name}
          </DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="space-y-2">
            <Sk className="h-8 w-full" />
            <Sk className="h-8 w-full" />
          </div>
        ) : error ? (
          <p className="text-danger text-sm">
            {extractApiErrorDetail(error) ?? 'Failed to load history'}
          </p>
        ) : !data?.length ? (
          <p className="text-tertiary text-sm">No history.</p>
        ) : (
          <div className="border-primary max-h-96 divide-y divide-(--ds-border-primary) overflow-y-auto rounded-md border">
            {data.map((v, idx) => (
              <VersionRow
                isCurrent={idx === 0}
                isPending={pending === v.version}
                isRestoring={restore.isPending}
                key={v.version}
                onConfirm={() => restore.mutate(v.version)}
                onRestore={() => setPending(v.version)}
                onToggleReveal={() =>
                  setRevealed((prev) => ({
                    ...prev,
                    [v.version]: !prev[v.version],
                  }))
                }
                revealed={Boolean(revealed[v.version])}
                version={v}
              />
            ))}
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}

function VersionRow({
  isCurrent,
  isPending,
  isRestoring,
  onConfirm,
  onRestore,
  onToggleReveal,
  revealed,
  version,
}: {
  isCurrent: boolean
  isPending: boolean
  isRestoring: boolean
  onConfirm: () => void
  onRestore: () => void
  onToggleReveal: () => void
  revealed: boolean
  version: ConfigVersionResponse
}) {
  const hasValue = version.value !== null
  const masked = version.secret && !revealed
  return (
    <div className="flex items-center gap-3 px-3 py-2 text-xs">
      <span className="text-secondary w-10 shrink-0 font-mono">
        v{version.version}
      </span>
      <div className="min-w-0 flex-1">
        <div
          className="text-primary truncate font-mono"
          data-ph-no-capture={version.secret || undefined}
        >
          {!hasValue ? (
            <span className="text-tertiary">Value hidden</span>
          ) : masked ? (
            maskSecret(version.value ?? '')
          ) : (
            version.value
          )}
        </div>
        <div className="text-tertiary">
          {version.last_modified &&
            parseServerTs(version.last_modified).toLocaleString()}
          {version.modified_by && ` · ${version.modified_by}`}
        </div>
      </div>
      {hasValue && version.secret && (
        <Button
          aria-label={revealed ? 'Hide value' : 'Reveal value'}
          className="h-7 px-1.5"
          onClick={onToggleReveal}
          size="sm"
          variant="ghost"
        >
          {revealed ? (
            <EyeOff className="size-3" />
          ) : (
            <Eye className="size-3" />
          )}
        </Button>
      )}
      {isCurrent ? (
        <span className="text-tertiary w-24 text-right">Current</span>
      ) : isPending ? (
        <Button
          className="w-24"
          disabled={isRestoring}
          onClick={onConfirm}
          size="sm"
        >
          Confirm
        </Button>
      ) : (
        <Button
          className="w-24"
          disabled={isRestoring}
          onClick={onRestore}
          size="sm"
          variant="outline"
        >
          <RotateCcw className="size-3" /> Restore
        </Button>
      )}
    </div>
  )
}
