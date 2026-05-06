import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteEnvironmentEdge,
  listEnvironmentEdges,
  listPluginEntities,
  setEnvironmentEdge,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { PluginEdge, PluginEdgeLabel, PluginEntity } from '@/types'

// Only ``environment`` anchors are wired up today; widen the union when
// projects/project-types/orgs gain edge endpoints.
export type AnchorKind = 'environment'

interface AnchorEdgesCardProps {
  anchor: { orgSlug: string; slug: string }
  anchorKind: AnchorKind
  edge: PluginEdgeLabel
  entityPluginSlug: string
  title?: string
}

const labelEntityName = (entity: PluginEntity): string => {
  const name = entity.name ?? entity.slug ?? entity.id
  return typeof name === 'string' ? name : String(entity.id)
}

const labelEntitySubtitle = (entity: PluginEntity): null | string => {
  const candidates = ['account_id', 'slug', 'description']
  for (const key of candidates) {
    const value = entity[key]
    if (typeof value === 'string' && value && value !== entity.name) {
      return value
    }
  }
  return null
}

export function AnchorEdgesCard({
  anchor,
  anchorKind,
  edge,
  entityPluginSlug,
  title,
}: AnchorEdgesCardProps) {
  const queryClient = useQueryClient()
  const targetLabel = edge.to_labels[0]
  const edgesKey = [
    'anchor-edges',
    anchorKind,
    anchor.orgSlug,
    anchor.slug,
    edge.name,
  ]

  const edgesQuery = useQuery<PluginEdge[]>({
    queryFn: ({ signal }) =>
      listEnvironmentEdges(anchor.orgSlug, anchor.slug, edge.name, signal),
    queryKey: edgesKey,
    staleTime: 30 * 1000,
  })

  const targetsQuery = useQuery<PluginEntity[]>({
    queryFn: ({ signal }) =>
      listPluginEntities(entityPluginSlug, targetLabel, signal),
    queryKey: ['plugin-entities', entityPluginSlug, targetLabel],
    staleTime: 30 * 1000,
  })

  const [pendingId, setPendingId] = useState<null | string>(null)

  const setMutation = useMutation({
    mutationFn: (targetId: string) =>
      setEnvironmentEdge(anchor.orgSlug, anchor.slug, edge.name, {
        target_id: targetId,
        target_label: targetLabel,
      }),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to set mapping')
    },
    onSuccess: () => {
      toast.success(`${edge.name} edge saved`)
      setPendingId(null)
      void queryClient.invalidateQueries({ queryKey: edgesKey })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () =>
      deleteEnvironmentEdge(anchor.orgSlug, anchor.slug, edge.name),
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to remove mapping')
    },
    onSuccess: () => {
      toast.success(`${edge.name} edge removed`)
      void queryClient.invalidateQueries({ queryKey: edgesKey })
    },
  })

  const targets = targetsQuery.data ?? []
  const current = edgesQuery.data?.[0] ?? null
  const submitting = setMutation.isPending || deleteMutation.isPending

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title ?? `${edge.name} → ${targetLabel}`}</CardTitle>
        <p className="mt-1 text-sm text-secondary">
          Map this {anchorKind} to a {targetLabel} via the{' '}
          <code className="text-xs">{edge.name}</code> edge.
        </p>
      </CardHeader>
      <CardContent className="space-y-4">
        {current ? (
          <div className="bg-secondary/30 rounded-md border px-4 py-3">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="font-medium text-primary">
                  {labelEntityName(current.target)}
                </div>
                {labelEntitySubtitle(current.target) && (
                  <div className="font-mono text-sm text-secondary">
                    {labelEntitySubtitle(current.target)}
                  </div>
                )}
              </div>
              <Button
                disabled={submitting}
                onClick={() => deleteMutation.mutate()}
                size="sm"
                variant="ghost"
              >
                <Trash2 className="mr-1 h-3.5 w-3.5" />
                Unmap
              </Button>
            </div>
          </div>
        ) : (
          <div className="text-sm text-secondary">
            Not mapped to any {targetLabel} yet.
          </div>
        )}

        {targets.length === 0 ? (
          <p className="text-sm text-tertiary">
            No {targetLabel} records have been registered.
          </p>
        ) : (
          <div className="flex items-center gap-3">
            <Select
              onValueChange={(value) => setPendingId(value)}
              value={pendingId ?? current?.target.id ?? ''}
            >
              <SelectTrigger className="w-[300px]">
                <SelectValue placeholder={`Choose a ${targetLabel}…`} />
              </SelectTrigger>
              <SelectContent>
                {targets.map((target) => (
                  <SelectItem key={target.id} value={target.id}>
                    {labelEntityName(target)}
                    {labelEntitySubtitle(target)
                      ? ` (${labelEntitySubtitle(target)})`
                      : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button
              disabled={
                submitting ||
                pendingId === null ||
                pendingId === current?.target.id
              }
              onClick={() => {
                if (pendingId) setMutation.mutate(pendingId)
              }}
              size="sm"
            >
              {current ? 'Change' : `Map ${targetLabel}`}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  )
}
