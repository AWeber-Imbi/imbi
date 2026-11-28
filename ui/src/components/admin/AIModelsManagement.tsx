import { useMemo, useState } from 'react'

import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { DollarSign, Plus } from 'lucide-react'
import { toast } from 'sonner'

import {
  createAIModel,
  createAIProvider,
  deleteAIModel,
  deleteAIProvider,
  deleteAIProviderCredentials,
  deleteAIProviderWorkloadIdentity,
  importAIModels,
  listAIProviderDrivers,
  listAIProviders,
  setAIProviderCredentials,
  setAIProviderWorkloadIdentity,
  updateAIModel,
  updateAIProvider,
} from '@/api/endpoints'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { useAIModels, useTeams } from '@/hooks/useOrgResources'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildDiffPatch } from '@/lib/json-patch'
import { queryKeys } from '@/lib/queryKeys'
import type {
  AIModel,
  AIModelImport,
  AIProvider,
  AIProviderCreate,
  AIProviderDriver,
  Team,
} from '@/types'

import { AdminSection } from './AdminSection'
import { CredentialsDialog } from './ai-models/CredentialsDialog'
import { decimalToNumber } from './ai-models/decimal'
import { DefaultModelSelect } from './ai-models/DefaultModelSelect'
import { DiscoverModelsDialog } from './ai-models/DiscoverModelsDialog'
import { ModelDialog, type ModelFormValues } from './ai-models/ModelDialog'
import { PriceSyncDialog } from './ai-models/PriceSyncDialog'
import {
  ProviderDialog,
  type ProviderFormValues,
} from './ai-models/ProviderDialog'
import { type ProviderRow, ProviderTable } from './ai-models/ProviderTable'

type ProviderFilter = 'all' | 'builtin' | 'custom' | 'missing-credentials'

const LIST_PATH = '/admin/ai-models'

// Stable empty-array references so an in-flight query does not hand the
// row memo a fresh array on every render.
const NO_DRIVERS: AIProviderDriver[] = []
const NO_MODELS: AIModel[] = []
const NO_PROVIDERS: AIProvider[] = []
const NO_TEAMS: Team[] = []

// The provider fields the edit dialog owns. `driver` is deliberately
// absent: models point at the provider and the request shape must not
// change under them.
const PROVIDER_PATCH_FIELDS = [
  'allow_insecure_http',
  'base_url',
  'description',
  'enabled',
  'name',
  'project_id',
  'region',
]

// The fields the edit dialog owns; anything else on the model node is
// server-managed and must not appear in the patch.
const MODEL_PATCH_FIELDS = [
  'access_scope',
  'allowed_team_ids',
  'cache_read_cost_per_million',
  'cache_write_1h_cost_per_million',
  'cache_write_cost_per_million',
  'context_window',
  'default_temperature',
  'default_top_p',
  'enabled',
  'input_cost_per_million',
  'kind',
  'max_output_tokens',
  'model_id',
  'model_type',
  'monthly_spend_cap',
  'name',
  'output_cost_per_million',
  'provider_id',
  'supports_forced_tool_choice',
  'supports_structured_output',
]

// fallow-ignore-next-line complexity
export function AIModelsManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  // The http:// flag controls where the key goes (ADR 0022 amendment).
  const canSetInsecureHttp = useHasPermission('ai_model:credentials', orgSlug)
  const navigate = useNavigate()
  const { action, slug } = useParams<{ action?: string; slug?: string }>()
  const [searchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const [searchQuery, setSearchQuery] = useState('')
  const [filter, setFilter] = useState<ProviderFilter>('all')
  const [expandKey, setExpandKey] = useState<null | string>(null)
  const [priceSyncOpen, setPriceSyncOpen] = useState(false)

  const driversQuery = useQuery({
    queryFn: ({ signal }) => listAIProviderDrivers(signal),
    queryKey: ['ai-provider-drivers'],
  })
  // The catalog belongs to the selected organization.
  const providersQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listAIProviders(orgSlug, signal),
    queryKey: queryKeys.aiProviders(orgSlug),
  })
  const modelsQuery = useAIModels(orgSlug)
  const teamsQuery = useTeams(orgSlug)

  const drivers = driversQuery.data ?? NO_DRIVERS
  const providers = providersQuery.data ?? NO_PROVIDERS
  const models = modelsQuery.data ?? NO_MODELS
  const teams = teamsQuery.data ?? NO_TEAMS

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.aiProviders(orgSlug) })
    queryClient.invalidateQueries({ queryKey: queryKeys.aiModels(orgSlug) })
  }
  const goToList = () => navigate(LIST_PATH)
  const closeAndRefresh = () => {
    invalidate()
    goToList()
  }

  // Every mutation toasts on failure. Several of these fire from a
  // dialog that closes on success, and the toggle reverts in place, so
  // without this a 403 or a 409 would be invisible.
  const onMutationError = (err: unknown) =>
    toast.error(extractApiErrorDetail(err))

  const createProviderMutation = useMutation({
    mutationFn: (values: AIProviderCreate) => createAIProvider(orgSlug, values),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const updateProviderMutation = useMutation({
    mutationFn: ({
      id,
      opened,
      values,
    }: {
      id: string
      opened?: AIProvider | null
      values: ProviderFormValues
    }) =>
      updateAIProvider(
        orgSlug,
        id,
        // Diff against the provider as the dialog opened it: a list
        // refresh while it is open must not put back a value that another
        // user changed (for example `allow_insecure_http`).
        buildDiffPatch(
          currentProviderState(opened ?? undefined),
          values as unknown as Record<string, unknown>,
          { fields: PROVIDER_PATCH_FIELDS },
        ),
      ),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const deleteProviderMutation = useMutation({
    mutationFn: (id: string) => deleteAIProvider(orgSlug, id),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const setCredentialsMutation = useMutation({
    mutationFn: ({ apiKey, id }: { apiKey: string; id: string }) =>
      setAIProviderCredentials(orgSlug, id, apiKey),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const removeCredentialsMutation = useMutation({
    mutationFn: (id: string) => deleteAIProviderCredentials(orgSlug, id),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const setWorkloadIdentityMutation = useMutation({
    mutationFn: ({
      body,
      id,
    }: {
      body: { target: Record<string, unknown> }
      id: string
    }) => setAIProviderWorkloadIdentity(orgSlug, id, body),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const removeWorkloadIdentityMutation = useMutation({
    mutationFn: (id: string) => deleteAIProviderWorkloadIdentity(orgSlug, id),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  // Clear every credential error before a new action, so the banner
  // shows only the result of the latest action.
  const resetCredentialErrors = () => {
    setCredentialsMutation.reset()
    removeCredentialsMutation.reset()
    setWorkloadIdentityMutation.reset()
    removeWorkloadIdentityMutation.reset()
  }

  const createModelMutation = useMutation({
    mutationFn: (values: ModelFormValues) =>
      createAIModel(orgSlug, {
        access_scope: values.access_scope,
        allowed_team_ids: values.allowed_team_ids,
        cache_read_cost_per_million: values.cache_read_cost_per_million,
        cache_write_1h_cost_per_million: values.cache_write_1h_cost_per_million,
        cache_write_cost_per_million: values.cache_write_cost_per_million,
        context_window: values.context_window,
        default_temperature: values.default_temperature,
        default_top_p: values.default_top_p,
        enabled: values.enabled,
        input_cost_per_million: values.input_cost_per_million,
        kind: values.kind,
        max_output_tokens: values.max_output_tokens,
        model_id: values.model_id,
        model_type: values.model_type,
        monthly_spend_cap: values.monthly_spend_cap,
        name: values.name,
        output_cost_per_million: values.output_cost_per_million,
        provider_id: values.provider_id,
        supports_forced_tool_choice: values.supports_forced_tool_choice,
        supports_structured_output: values.supports_structured_output,
      }),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const updateModelMutation = useMutation({
    mutationFn: ({ id, values }: { id: string; values: ModelFormValues }) =>
      updateAIModel(
        orgSlug,
        id,
        buildDiffPatch(
          currentModelState(models.find((m) => m.id === id)),
          values as unknown as Record<string, unknown>,
          { fields: MODEL_PATCH_FIELDS },
        ),
      ),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const deleteModelMutation = useMutation({
    mutationFn: (id: string) => deleteAIModel(orgSlug, id),
    onError: onMutationError,
    onSuccess: closeAndRefresh,
  })
  const toggleModelMutation = useMutation({
    mutationFn: ({ enabled, id }: { enabled: boolean; id: string }) =>
      updateAIModel(orgSlug, id, [
        { op: 'replace', path: '/enabled', value: enabled },
      ]),
    onError: onMutationError,
    onSuccess: invalidate,
  })

  const importModelsMutation = useMutation({
    mutationFn: ({
      models: selected,
      providerId,
    }: {
      models: AIModelImport[]
      providerId: string
    }) => importAIModels(orgSlug, providerId, { models: selected }),
    onError: onMutationError,
    onSuccess: (result, { providerId }) => {
      toast.success(importSummary(result.created.length, result.skipped.length))
      setExpandKey(providerId)
      closeAndRefresh()
    },
  })

  const rows = useMemo(
    () => buildRows(providers, models, drivers),
    [providers, models, drivers],
  )
  const visibleRows = rows.filter(
    (row) => matchesFilter(row, filter) && matchesQuery(row, searchQuery),
  )

  const editingModel =
    action === 'edit' && slug
      ? (models.find((m) => m.id === slug) ?? null)
      : null
  const credentialsProvider =
    action === 'credentials' && slug
      ? (providers.find((p) => p.id === slug) ?? null)
      : null
  const discoverProvider =
    action === 'discover' && slug
      ? (providers.find((p) => p.id === slug) ?? null)
      : null
  const editingProvider =
    action === 'edit-provider' && slug
      ? (providers.find((p) => p.id === slug) ?? null)
      : null

  // Dialogs seed their fields once on mount, so hold them back until the
  // lists they read are in hand. Without this a cold load or a reload of
  // a deep link opens an empty form that never recovers.
  const listsReady = driversQuery.isSuccess && providersQuery.isSuccess
  const providerDialogOpen = slug === 'new-provider' && listsReady
  const providerEditOpen = action === 'edit-provider' && listsReady
  const modelDialogOpen =
    (slug === 'new-model' || action === 'edit') && listsReady

  // A stale or mistyped id resolves to nothing once the list has loaded.
  const missingModel =
    action === 'edit' && slug && modelsQuery.isSuccess && !editingModel
  const missingProvider =
    (action === 'edit-provider' ||
      action === 'credentials' ||
      action === 'discover') &&
    slug &&
    providersQuery.isSuccess &&
    !providers.some((p) => p.id === slug)

  const listError =
    providersQuery.error ??
    modelsQuery.error ??
    driversQuery.error ??
    teamsQuery.error

  return (
    <div className="space-y-6">
      <p className="text-secondary max-w-3xl text-sm">
        Providers and models of this organization. Enabling a model makes it
        selectable in prompts, assistants and automations; disabling it hides it
        everywhere without deleting its configuration.
      </p>

      {orgSlug && (
        <div className="flex items-center gap-3">
          <span className="text-secondary text-sm">
            Default model for {selectedOrganization?.name ?? orgSlug}
          </span>
          <DefaultModelSelect className="w-72" orgSlug={orgSlug} />
        </div>
      )}

      {(missingModel || missingProvider) && (
        <Alert variant="warning">
          That {missingModel ? 'model' : 'provider'} no longer exists.{' '}
          <Button
            className="h-auto p-0 align-baseline"
            onClick={goToList}
            variant="link"
          >
            Back to the list
          </Button>
        </Alert>
      )}

      <AdminSection
        createLabel="Add model"
        error={listError}
        errorTitle="Failed to load AI models"
        headerActions={
          <>
            <Button onClick={() => setPriceSyncOpen(true)} variant="secondary">
              <DollarSign className="mr-2 size-4" />
              Sync prices
            </Button>
            <Button
              onClick={() => navigate(`${LIST_PATH}/new-provider`)}
              variant="secondary"
            >
              <Plus className="mr-2 size-4" />
              Add provider
            </Button>
          </>
        }
        headerExtras={
          <Select
            onValueChange={(v) => setFilter(v as ProviderFilter)}
            value={filter}
          >
            <SelectTrigger aria-label="Filter providers" className="w-56">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All providers</SelectItem>
              <SelectItem value="builtin">Built-in only</SelectItem>
              <SelectItem value="custom">Custom only</SelectItem>
              <SelectItem value="missing-credentials">
                Missing credentials
              </SelectItem>
            </SelectContent>
          </Select>
        }
        onCreate={() => navigate(`${LIST_PATH}/new-model`)}
        onSearchChange={setSearchQuery}
        search={searchQuery}
        searchPlaceholder="Search providers and models…"
      >
        <ProviderTable
          expandKey={expandKey}
          loading={providersQuery.isLoading || modelsQuery.isLoading}
          onAddModel={(providerId) =>
            navigate(`${LIST_PATH}/new-model?provider=${providerId}`)
          }
          onClearFilters={() => {
            setSearchQuery('')
            setFilter('all')
          }}
          onCredentials={(providerId) =>
            navigate(`${LIST_PATH}/${providerId}/credentials`)
          }
          onDiscover={(providerId) =>
            navigate(`${LIST_PATH}/${providerId}/discover`)
          }
          onEditModel={(modelId) => navigate(`${LIST_PATH}/${modelId}/edit`)}
          onEditProvider={(providerId) =>
            navigate(`${LIST_PATH}/${providerId}/edit-provider`)
          }
          onSetUpDriver={(driverSlug) =>
            navigate(`${LIST_PATH}/new-provider?driver=${driverSlug}`)
          }
          onToggleModel={(model, enabled) =>
            toggleModelMutation.mutate({ enabled, id: model.id })
          }
          rows={visibleRows}
          togglePendingId={
            toggleModelMutation.isPending
              ? (toggleModelMutation.variables?.id ?? null)
              : null
          }
        />
      </AdminSection>

      {providerDialogOpen && (
        <ProviderDialog
          canSetInsecureHttp={canSetInsecureHttp}
          defaultDriver={searchParams.get('driver') ?? undefined}
          drivers={drivers}
          error={createProviderMutation.error}
          isPending={createProviderMutation.isPending}
          onClose={goToList}
          onSubmit={(values) =>
            createProviderMutation.mutate({
              allow_insecure_http: values.allow_insecure_http,
              api_key: values.api_key,
              base_url: values.base_url,
              description: values.description,
              driver: values.driver,
              name: values.name,
              project_id: values.project_id,
              region: values.region,
            })
          }
          open
        />
      )}

      {providerEditOpen && editingProvider && (
        <ProviderDialog
          canSetInsecureHttp={canSetInsecureHttp}
          deleteBlockedReason={
            editingProvider.model_count > 0
              ? 'Delete or move its models first'
              : undefined
          }
          drivers={drivers}
          error={updateProviderMutation.error ?? deleteProviderMutation.error}
          isPending={
            updateProviderMutation.isPending || deleteProviderMutation.isPending
          }
          key={editingProvider.id}
          onClose={goToList}
          onDelete={() => deleteProviderMutation.mutate(editingProvider.id)}
          onSubmit={(values, opened) =>
            updateProviderMutation.mutate({
              id: editingProvider.id,
              opened,
              values,
            })
          }
          open
          provider={editingProvider}
        />
      )}

      {modelDialogOpen && (action !== 'edit' || editingModel) && (
        <ModelDialog
          defaultProviderId={searchParams.get('provider') ?? undefined}
          drivers={drivers}
          error={
            createModelMutation.error ??
            updateModelMutation.error ??
            deleteModelMutation.error
          }
          isPending={
            createModelMutation.isPending ||
            updateModelMutation.isPending ||
            deleteModelMutation.isPending
          }
          key={editingModel?.id ?? 'create'}
          model={editingModel}
          onClose={goToList}
          onDelete={(model) => deleteModelMutation.mutate(model.id)}
          onSubmit={(values) => {
            if (editingModel) {
              updateModelMutation.mutate({ id: editingModel.id, values })
            } else {
              createModelMutation.mutate(values)
            }
          }}
          open
          providers={providers}
          teams={teams}
        />
      )}

      {credentialsProvider && (
        <CredentialsDialog
          error={
            setCredentialsMutation.error ??
            removeCredentialsMutation.error ??
            setWorkloadIdentityMutation.error ??
            removeWorkloadIdentityMutation.error
          }
          isPending={
            setCredentialsMutation.isPending ||
            removeCredentialsMutation.isPending ||
            setWorkloadIdentityMutation.isPending ||
            removeWorkloadIdentityMutation.isPending
          }
          onClose={goToList}
          onRemove={() => {
            resetCredentialErrors()
            removeCredentialsMutation.mutate(credentialsProvider.id)
          }}
          onRemoveWorkloadIdentity={() => {
            resetCredentialErrors()
            removeWorkloadIdentityMutation.mutate(credentialsProvider.id)
          }}
          onSave={(apiKey) => {
            resetCredentialErrors()
            setCredentialsMutation.mutate({
              apiKey,
              id: credentialsProvider.id,
            })
          }}
          onSaveWorkloadIdentity={(body) => {
            resetCredentialErrors()
            setWorkloadIdentityMutation.mutate({
              body,
              id: credentialsProvider.id,
            })
          }}
          open
          provider={credentialsProvider}
        />
      )}

      {discoverProvider && (
        <DiscoverModelsDialog
          importError={importModelsMutation.error}
          isImporting={importModelsMutation.isPending}
          key={discoverProvider.id}
          onClose={goToList}
          onImport={(selected) =>
            importModelsMutation.mutate({
              models: selected,
              providerId: discoverProvider.id,
            })
          }
          open
          orgSlug={orgSlug}
          provider={discoverProvider}
        />
      )}

      {priceSyncOpen && (
        <PriceSyncDialog
          onApplied={(result) => {
            toast.success(
              `Updated prices for ${result.updated.length} model${result.updated.length === 1 ? '' : 's'}`,
            )
            setPriceSyncOpen(false)
            invalidate()
          }}
          onClose={() => setPriceSyncOpen(false)}
          orgSlug={orgSlug}
        />
      )}
    </div>
  )
}

function buildRows(
  providers: AIProvider[],
  models: AIModel[],
  drivers: ProviderRow['driver'][],
): ProviderRow[] {
  const driverList = drivers.filter((d) => d !== undefined)
  const configured = [...providers]
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((provider) => ({
      driver: driverList.find((d) => d.slug === provider.driver),
      key: provider.id,
      models: models.filter((model) => model.provider_id === provider.id),
      provider,
    }))
  const configuredDrivers = new Set(providers.map((p) => p.driver))
  const ghosts = driverList
    .filter(
      (d) => d.slug !== 'openai_compatible' && !configuredDrivers.has(d.slug),
    )
    .map((driver) => ({
      driver,
      key: driver.slug,
      models: [],
      provider: null,
    }))
  return [...configured, ...ghosts]
}

function currentModelState(
  model: AIModel | undefined,
): Record<string, unknown> {
  if (!model) return {}
  return {
    access_scope: model.access_scope,
    allowed_team_ids: model.allowed_teams.map((team) => team.id),
    cache_read_cost_per_million: decimalToNumber(
      model.cache_read_cost_per_million,
    ),
    cache_write_1h_cost_per_million: decimalToNumber(
      model.cache_write_1h_cost_per_million,
    ),
    cache_write_cost_per_million: decimalToNumber(
      model.cache_write_cost_per_million,
    ),
    context_window: model.context_window,
    default_temperature: model.default_temperature,
    default_top_p: model.default_top_p,
    enabled: model.enabled,
    input_cost_per_million: decimalToNumber(model.input_cost_per_million),
    kind: model.kind,
    max_output_tokens: model.max_output_tokens,
    model_id: model.model_id,
    model_type: model.model_type,
    monthly_spend_cap: decimalToNumber(model.monthly_spend_cap),
    name: model.name,
    output_cost_per_million: decimalToNumber(model.output_cost_per_million),
    provider_id: model.provider_id,
    supports_forced_tool_choice: model.supports_forced_tool_choice,
    supports_structured_output: model.supports_structured_output,
  }
}

function currentProviderState(
  provider: AIProvider | undefined,
): Record<string, unknown> {
  if (!provider) return {}
  return {
    allow_insecure_http: provider.allow_insecure_http ?? false,
    base_url: provider.base_url,
    description: provider.description,
    enabled: provider.enabled,
    name: provider.name,
    project_id: provider.project_id,
    region: provider.region,
  }
}

function importSummary(created: number, skipped: number): string {
  const head = `Imported ${created} model${created === 1 ? '' : 's'}`
  return skipped === 0 ? head : `${head}; ${skipped} already configured`
}

function matchesFilter(row: ProviderRow, filter: ProviderFilter): boolean {
  if (filter === 'builtin') {
    return row.provider ? row.provider.is_builtin_driver : true
  }
  if (filter === 'custom') {
    return !!row.provider && !row.provider.is_builtin_driver
  }
  if (filter === 'missing-credentials') {
    if (!row.provider) return true
    return row.provider.auth_kind === 'none'
  }
  return true
}

function matchesQuery(row: ProviderRow, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  const name = row.provider?.name ?? row.driver?.name ?? ''
  if (name.toLowerCase().includes(q)) return true
  return row.models.some(
    (model) =>
      model.name.toLowerCase().includes(q) ||
      model.model_id.toLowerCase().includes(q),
  )
}
