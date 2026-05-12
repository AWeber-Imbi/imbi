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
import { Input } from '@/components/ui/input'
import { extractApiErrorDetail } from '@/lib/apiError'
import {
  findOrCreatePluginEntityByKey,
  naturalKeyField,
} from '@/lib/plugin-entities'
import { queryKeys } from '@/lib/queryKeys'
import type {
  InstalledPlugin,
  PluginEdge,
  PluginEdgeLabel,
  PluginEntity,
} from '@/types'

interface AnchorEdgesCardProps {
  anchor: { orgSlug: string; slug: string }
  anchorKind: AnchorKind
  edge: PluginEdgeLabel
  entityPluginSlug: string
  manifest: InstalledPlugin
  title?: string
}

// Only ``environment`` anchors are wired up today; widen the union when
// projects/project-types/orgs gain edge endpoints.
type AnchorKind = 'environment'

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
  manifest,
  title,
}: AnchorEdgesCardProps) {
  const queryClient = useQueryClient()
  const targetLabel = edge.to_labels[0]
  const targetVlabel = manifest.vertex_labels?.find(
    (v) => v.name === targetLabel,
  )
  const targetDisplay = targetVlabel?.display_name || targetLabel
  const naturalKey = naturalKeyField(targetVlabel)
  const edgesKey = queryKeys.anchorEdges(
    anchorKind,
    anchor.orgSlug,
    anchor.slug,
    edge.name,
  )

  const edgesQuery = useQuery<PluginEdge[]>({
    queryFn: ({ signal }) =>
      listEnvironmentEdges(anchor.orgSlug, anchor.slug, edge.name, signal),
    queryKey: edgesKey,
    staleTime: 30 * 1000,
  })

  const targetsQuery = useQuery<PluginEntity[]>({
    queryFn: ({ signal }) =>
      listPluginEntities(entityPluginSlug, targetLabel, signal),
    queryKey: queryKeys.pluginEntities(entityPluginSlug, targetLabel),
    staleTime: 30 * 1000,
  })

  const [draft, setDraft] = useState<null | string>(null)

  const setMutation = useMutation({
    mutationFn: async (pasted: string) => {
      if (!naturalKey) {
        throw new Error(
          `Plugin ${manifest.slug} declared no unique key for ${targetLabel}; ` +
            `cannot resolve "${pasted}".`,
        )
      }
      const target = await findOrCreatePluginEntityByKey({
        existing: targetsQuery.data,
        keyField: naturalKey,
        label: targetLabel,
        pluginSlug: entityPluginSlug,
        value: pasted,
      })
      await queryClient.invalidateQueries({
        queryKey: queryKeys.pluginEntities(entityPluginSlug, targetLabel),
      })
      return setEnvironmentEdge(anchor.orgSlug, anchor.slug, edge.name, {
        target_id: target.id,
        target_label: targetLabel,
      })
    },
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to set mapping')
    },
    onSuccess: () => {
      toast.success(`${edge.name} edge saved`)
      setDraft(null)
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

  const current = edgesQuery.data?.[0] ?? null
  const submitting = setMutation.isPending || deleteMutation.isPending
  const currentTargetKey = naturalKey ? current?.target[naturalKey] : undefined
  const currentKey =
    typeof currentTargetKey === 'string' ? currentTargetKey : ''
  const inputValue = draft ?? currentKey
  const dirty = inputValue !== currentKey

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title ?? `${edge.name} → ${targetDisplay}`}</CardTitle>
        <p className="mt-1 text-sm text-secondary">
          Map this {anchorKind} to a {targetDisplay} via the{' '}
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
            Not mapped to any {targetDisplay} yet.
          </div>
        )}

        <div className="flex items-center gap-3">
          <Input
            className="w-[300px]"
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              naturalKey ? `Paste ${naturalKey}` : `Paste ${targetDisplay}`
            }
            value={inputValue}
          />
          <Button
            disabled={submitting || !dirty || inputValue.trim() === ''}
            onClick={() => setMutation.mutate(inputValue.trim())}
            size="sm"
          >
            {current ? 'Change' : `Map ${targetDisplay}`}
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
