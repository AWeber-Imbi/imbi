import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  listEnvironments,
  listPluginEdgesByOrg,
  listPluginEntities,
  setEnvironmentEdge,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { extractApiErrorDetail } from '@/lib/apiError'
import {
  findOrCreatePluginEntityByKey,
  naturalKeyField,
} from '@/lib/plugin-entities'
import { queryKeys } from '@/lib/queryKeys'
import type {
  Environment,
  InstalledPlugin,
  PluginEdge,
  PluginEdgeLabel,
  PluginEntity,
} from '@/types'

interface EnvironmentEdgeTableProps {
  edge: PluginEdgeLabel
  entityPluginSlug: string
  manifest: InstalledPlugin
  orgSlug: string
}

interface ServicePluginEdgesCardProps {
  manifest: InstalledPlugin
  orgSlug: string
}

export function ServicePluginEdgesCard({
  manifest,
  orgSlug,
}: ServicePluginEdgesCardProps) {
  // Only ``Environment`` anchors are wired up today; widen the filter
  // when projects/orgs gain edge endpoints.
  const edges = (manifest.edge_labels ?? []).filter((e) =>
    e.from_labels.includes('Environment'),
  )

  if (edges.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Edge mappings</CardTitle>
        <CardDescription>
          Operational mappings between {orgSlug} entities and {manifest.name}{' '}
          records. Changes here are scoped to the current organization.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {edges.map((edge) => (
          <EnvironmentEdgeTable
            edge={edge}
            entityPluginSlug={manifest.slug}
            key={edge.name}
            manifest={manifest}
            orgSlug={orgSlug}
          />
        ))}
      </CardContent>
    </Card>
  )
}

function EnvironmentEdgeTable({
  edge,
  entityPluginSlug,
  manifest,
  orgSlug,
}: EnvironmentEdgeTableProps) {
  const queryClient = useQueryClient()
  const targetLabel = edge.to_labels[0]
  const targetVlabel = manifest.vertex_labels?.find(
    (v) => v.name === targetLabel,
  )
  const targetDisplay = targetVlabel?.display_name || targetLabel
  const naturalKey = naturalKeyField(targetVlabel)

  const environmentsQuery = useQuery<Environment[]>({
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
    staleTime: 30 * 1000,
  })
  const targetsQuery = useQuery<PluginEntity[]>({
    queryFn: ({ signal }) =>
      listPluginEntities(entityPluginSlug, targetLabel, signal),
    queryKey: queryKeys.pluginEntities(entityPluginSlug, targetLabel),
    staleTime: 30 * 1000,
  })

  const environments = environmentsQuery.data ?? []
  const edgesByEnvQuery = useQuery<Record<string, PluginEdge[]>>({
    queryFn: ({ signal }) =>
      listPluginEdgesByOrg(entityPluginSlug, edge.name, orgSlug, signal),
    queryKey: queryKeys.pluginEdgesByOrg(entityPluginSlug, edge.name, orgSlug),
    staleTime: 30 * 1000,
  })

  const [pendingValue, setPendingValue] = useState<Record<string, string>>({})

  const mapMutation = useMutation({
    mutationFn: async ({
      envSlug,
      pasted,
    }: {
      envSlug: string
      pasted: string
    }) => {
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
      return setEnvironmentEdge(orgSlug, envSlug, edge.name, {
        target_id: target.id,
        target_label: targetLabel,
      })
    },
    onError: (err) => {
      toast.error(extractApiErrorDetail(err) ?? 'Failed to set mapping')
    },
    onSuccess: (_, { envSlug }) => {
      toast.success('Mapping saved')
      setPendingValue((s) => {
        const next = { ...s }
        delete next[envSlug]
        return next
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.pluginEdgesByOrg(
          entityPluginSlug,
          edge.name,
          orgSlug,
        ),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.anchorEdges(
          'environment',
          orgSlug,
          envSlug,
          edge.name,
        ),
      })
    },
  })

  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-3">
        <h3 className="text-sm font-medium text-primary">
          Environment → {targetDisplay}
        </h3>
        <code className="text-xs text-tertiary">{edge.name}</code>
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Environment</TableHead>
              <TableHead>{targetDisplay}</TableHead>
              <TableHead className="w-24 text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {environments.length === 0 ? (
              <TableRow>
                <TableCell
                  className="py-6 text-center text-sm text-secondary"
                  colSpan={3}
                >
                  No environments in this organization yet.
                </TableCell>
              </TableRow>
            ) : (
              environments.map((env) => {
                const edges = edgesByEnvQuery.data?.[env.slug]
                const current = edges?.[0] ?? null
                const currentTargetKey = naturalKey
                  ? current?.target[naturalKey]
                  : undefined
                const currentKey =
                  typeof currentTargetKey === 'string' ? currentTargetKey : ''
                const draft = pendingValue[env.slug] ?? currentKey
                const submitting = mapMutation.isPending
                const dirty = draft !== currentKey
                return (
                  <TableRow key={env.slug}>
                    <TableCell>
                      <div className="font-medium text-primary">{env.name}</div>
                      <code className="text-xs text-tertiary">{env.slug}</code>
                    </TableCell>
                    <TableCell>
                      <Input
                        onChange={(e) =>
                          setPendingValue((s) => ({
                            ...s,
                            [env.slug]: e.target.value,
                          }))
                        }
                        placeholder={
                          naturalKey
                            ? `Paste ${naturalKey}`
                            : `Paste ${targetDisplay}`
                        }
                        value={draft}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end">
                        <Button
                          disabled={submitting || !dirty || draft.trim() === ''}
                          onClick={() =>
                            mapMutation.mutate({
                              envSlug: env.slug,
                              pasted: draft.trim(),
                            })
                          }
                          size="sm"
                        >
                          {current ? 'Change' : 'Map'}
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                )
              })
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
