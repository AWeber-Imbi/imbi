import { Fragment, useEffect, useState } from 'react'

import {
  ChevronDown,
  ChevronRight,
  KeyRound,
  Pencil,
  Plus,
  RefreshCw,
  Search,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { AIModel, AIProvider, AIProviderDriver } from '@/types'

import { decimalToNumber } from './decimal'

/**
 * One line of the provider table. `provider` is null for a built-in
 * driver nobody has configured yet — those render as ghost rows with a
 * "Set up" action instead of credentials and models.
 */
export interface ProviderRow {
  driver: AIProviderDriver | undefined
  key: string
  models: AIModel[]
  provider: AIProvider | null
}

interface CredentialsCellProps {
  provider: AIProvider | null
}

interface ModelRowProps {
  isTogglePending: boolean
  model: AIModel
  onEditModel: (modelId: string) => void
  onToggleModel: (model: AIModel, enabled: boolean) => void
}

interface ProviderTableProps {
  /** Row key to force open, e.g. after an import lands. */
  expandKey?: null | string
  loading: boolean
  onAddModel: (providerId: string) => void
  onClearFilters: () => void
  onCredentials: (providerId: string) => void
  onDiscover: (providerId: string) => void
  onEditModel: (modelId: string) => void
  onEditProvider: (providerId: string) => void
  onSetUpDriver: (driverSlug: string) => void
  onToggleModel: (model: AIModel, enabled: boolean) => void
  rows: ProviderRow[]
  /** Id of the model whose enabled toggle is in flight, if any. */
  togglePendingId: null | string
}

export function ProviderTable({
  expandKey,
  loading,
  onAddModel,
  onClearFilters,
  onCredentials,
  onDiscover,
  onEditModel,
  onEditProvider,
  onSetUpDriver,
  onToggleModel,
  rows,
  togglePendingId,
}: ProviderTableProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!expandKey) return
    setExpanded((current) =>
      current.has(expandKey) ? current : new Set(current).add(expandKey),
    )
  }, [expandKey])

  const toggleExpanded = (key: string) => {
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  if (!loading && rows.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center py-16 text-center">
          <div className="bg-secondary text-tertiary mb-4 flex size-12 items-center justify-center rounded-xl">
            <Search className="size-6" />
          </div>
          <div className="text-primary text-base font-medium">
            No providers match
          </div>
          <Button className="mt-4" onClick={onClearFilters} variant="outline">
            Clear filters
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-8" />
              <TableHead>Provider</TableHead>
              <TableHead>Base URL</TableHead>
              <TableHead>Credentials</TableHead>
              <TableHead className="text-right">Models</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody aria-busy={loading || undefined}>
            {loading && rows.length === 0 ? (
              <TableRow>
                <TableCell
                  className="text-tertiary py-12 text-center"
                  colSpan={6}
                >
                  Loading providers…
                </TableCell>
              </TableRow>
            ) : (
              rows.map((row) => {
                const isOpen = expanded.has(row.key)
                const name = row.provider?.name ?? row.driver?.name ?? row.key
                const description =
                  row.provider?.description ?? row.driver?.description ?? null
                const baseUrl =
                  row.provider?.base_url ?? row.driver?.default_base_url ?? null
                // Discovery needs a configured provider, a stored key,
                // and a driver whose list-models API Imbi can call.
                const canDiscover =
                  !!row.provider &&
                  row.provider.has_credentials &&
                  (row.driver?.supports_discovery ?? false)
                return (
                  <Fragment key={row.key}>
                    <TableRow
                      className={cn(
                        'cursor-pointer',
                        !row.provider && 'text-tertiary',
                      )}
                      onClick={() => toggleExpanded(row.key)}
                    >
                      <TableCell className="pr-0">
                        <Button
                          aria-expanded={isOpen}
                          aria-label={`${isOpen ? 'Collapse' : 'Expand'} ${name}`}
                          className="size-6 p-0"
                          onClick={(e) => {
                            e.stopPropagation()
                            toggleExpanded(row.key)
                          }}
                          size="icon"
                          variant="ghost"
                        >
                          {isOpen ? (
                            <ChevronDown className="size-4" />
                          ) : (
                            <ChevronRight className="size-4" />
                          )}
                        </Button>
                      </TableCell>
                      <TableCell>
                        <div className="text-primary font-medium">{name}</div>
                        {description && (
                          <div className="text-tertiary max-w-sm truncate text-sm">
                            {description}
                          </div>
                        )}
                      </TableCell>
                      <TableCell>
                        <span
                          className="text-secondary block max-w-[16rem] truncate font-mono text-xs"
                          title={baseUrl ?? undefined}
                        >
                          {baseUrl ?? '—'}
                        </span>
                      </TableCell>
                      <TableCell>
                        <CredentialsCell provider={row.provider} />
                      </TableCell>
                      <TableCell className="text-right">
                        {row.provider ? (
                          <span className="text-secondary font-mono text-sm tabular-nums">
                            {row.provider.enabled_model_count} /{' '}
                            {row.provider.model_count}
                          </span>
                        ) : (
                          <span className="text-tertiary">—</span>
                        )}
                      </TableCell>
                      <TableCell
                        className="text-right"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {row.provider ? (
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              aria-label={`Edit ${name}`}
                              onClick={() => onEditProvider(row.provider!.id)}
                              size="sm"
                              variant="ghost"
                            >
                              <Pencil className="size-4" />
                            </Button>
                            <Button
                              aria-label={`Credentials for ${name}`}
                              onClick={() => onCredentials(row.provider!.id)}
                              size="sm"
                              variant="ghost"
                            >
                              <KeyRound className="size-4" />
                            </Button>
                            {canDiscover && (
                              <Button
                                aria-label={`Discover models from ${name}`}
                                onClick={() => onDiscover(row.provider!.id)}
                                size="sm"
                                variant="ghost"
                              >
                                <RefreshCw className="size-4" />
                              </Button>
                            )}
                            <Button
                              aria-label={`Add model to ${name}`}
                              onClick={() => onAddModel(row.provider!.id)}
                              size="sm"
                              variant="ghost"
                            >
                              <Plus className="size-4" />
                            </Button>
                          </div>
                        ) : (
                          <Button
                            onClick={() => onSetUpDriver(row.key)}
                            size="sm"
                            variant="outline"
                          >
                            Set up
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                    {isOpen && (
                      <TableRow>
                        <TableCell className="bg-secondary p-0" colSpan={6}>
                          {row.provider ? (
                            <div className="px-6 py-3">
                              {row.models.length === 0 ? (
                                <p className="text-tertiary py-2 text-sm">
                                  No models configured for this provider yet.
                                </p>
                              ) : (
                                <div className="divide-tertiary divide-y">
                                  {row.models.map((model) => (
                                    <ModelRow
                                      isTogglePending={
                                        togglePendingId === model.id
                                      }
                                      key={model.id}
                                      model={model}
                                      onEditModel={onEditModel}
                                      onToggleModel={onToggleModel}
                                    />
                                  ))}
                                </div>
                              )}
                              <div className="mt-2 flex items-center gap-1">
                                <Button
                                  onClick={() => onAddModel(row.provider!.id)}
                                  size="sm"
                                  variant="ghost"
                                >
                                  <Plus className="mr-1.5 size-3.5" />
                                  Add model to {name}
                                </Button>
                                {canDiscover && (
                                  <Button
                                    onClick={() => onDiscover(row.provider!.id)}
                                    size="sm"
                                    variant="ghost"
                                  >
                                    <RefreshCw className="mr-1.5 size-3.5" />
                                    Import from {name}
                                  </Button>
                                )}
                              </div>
                            </div>
                          ) : (
                            <p className="text-tertiary px-6 py-4 text-sm">
                              This provider is not configured yet. Set it up to
                              add models under it.
                            </p>
                          )}
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                )
              })
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

const currency = new Intl.NumberFormat('en-US', {
  currency: 'USD',
  maximumFractionDigits: 0,
  style: 'currency',
})

function CredentialsCell({ provider }: CredentialsCellProps) {
  if (!provider) {
    return <Badge variant="neutral">Not configured</Badge>
  }
  if (provider.auth_kind === 'iam') {
    return <Badge variant="info">IAM role</Badge>
  }
  if (provider.has_credentials) {
    return (
      <span className="flex items-center gap-2">
        <Badge variant="success">Key set</Badge>
        {provider.credential_hint && (
          <span className="text-tertiary font-mono text-xs">
            ••••{provider.credential_hint}
          </span>
        )}
      </span>
    )
  }
  return <Badge variant="warning">No key</Badge>
}

// The API renders Decimal as a JSON string, so coerce before formatting.
function formatCap(cap: AIModel['monthly_spend_cap']): string {
  const value = decimalToNumber(cap)
  return value === null ? '—' : `${currency.format(value)}/mo`
}

function ModelRow({
  isTogglePending,
  model,
  onEditModel,
  onToggleModel,
}: ModelRowProps) {
  return (
    <div
      className={cn(
        'flex items-center gap-4 py-2',
        !model.enabled && 'opacity-55',
      )}
    >
      <div className="min-w-0 flex-1">
        <div className="text-primary text-sm font-medium">{model.name}</div>
        <div className="text-tertiary truncate font-mono text-xs">
          {model.model_id}
        </div>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-1">
        {teamChips(model).map((chip) => (
          <Badge key={chip} variant="neutral">
            {chip}
          </Badge>
        ))}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Switch
          aria-label={`${model.enabled ? 'Disable' : 'Enable'} ${model.name}`}
          checked={model.enabled}
          disabled={isTogglePending}
          onCheckedChange={(enabled) => onToggleModel(model, enabled)}
        />
        <span className="text-tertiary w-14 text-xs">
          {model.enabled ? 'Enabled' : 'Disabled'}
        </span>
      </div>
      <span className="text-tertiary w-24 shrink-0 text-right font-mono text-xs tabular-nums">
        {formatCap(model.monthly_spend_cap)}
      </span>
      <Button
        aria-label={`Edit ${model.name}`}
        onClick={() => onEditModel(model.id)}
        size="sm"
        variant="ghost"
      >
        <Pencil className="size-4" />
      </Button>
    </div>
  )
}

function teamChips(model: AIModel): string[] {
  if (model.access_scope === 'organization') return ['All teams']
  const names = model.allowed_teams.map((team) => team.name)
  if (names.length <= 2) return names
  return [names[0], names[1], `+${names.length - 2}`]
}
