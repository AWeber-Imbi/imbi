import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import {
  CheckCircle2,
  Clock,
  ExternalLink,
  LoaderCircle,
  type LucideIcon,
  Plus,
  RotateCcw,
  Trash2,
  XCircle,
} from 'lucide-react'

import {
  listEnvironments,
  type ProjectSchemaResponse,
  type ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import { AttributeValue } from '@/components/ui/attribute-value'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { isFieldEditable } from '@/components/ui/inline-edit/field-policy'
import { InlineField } from '@/components/ui/inline-edit/InlineField'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { UserIdentity } from '@/components/ui/user-identity'
import { useEnvironmentEdgePatch } from '@/hooks/useEnvironmentEdgePatch'
import { useLoginToEmail } from '@/hooks/useLoginToEmail'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { formatFieldKey } from '@/lib/project-field-formatting'
import { sanitizeHttpUrl } from '@/lib/utils'
import type { DeploymentStatus, Project } from '@/types'

interface DeploymentInfo {
  committish: string
  // Deployer of the latest deploy event (remote actor); null for in-product.
  performedBy: null | string
  // Email of the deployer when resolved to an Imbi user — drives Gravatar +
  // profile link; null for unresolved remote logins.
  performedByEmail: null | string
  status: string
  tag: null | string
  updated: string
}

// Shared overline label style for the per-environment attribute cells.
const OVERLINE_CLASS =
  'text-tertiary mb-1.5 text-[10.5px] font-semibold tracking-[0.06em] uppercase'

type Environment = NonNullable<Project['environments']>[number]

interface ProjectEnvironmentsCardProps {
  deploymentStatus: Record<string, DeploymentInfo>
  environments: Environment[]
  orgSlug: string
  projectId: string
  // Project schema; its ``environment``-scoped sections supply the blueprint
  // defs (type/format + x-ui color/icon maps) for the edge attributes so they
  // render with the same display logic as project attributes.
  projectSchema?: ProjectSchemaResponse
}

// URL is a base edge property (always present on the DEPLOYED_IN model); used
// when the project's blueprints don't supply an explicit def for it.
const URL_DEF: ProjectSchemaSectionProperty = { format: 'uri', type: 'string' }

// Release lifecycle states for the project -> environment deployment edge.
// Keyed by the ``DeploymentStatus`` enum (the ``current_status`` recorded on
// the release -> environment edge), so the badges stay in lockstep with the
// backend enum.
const RELEASE_STATUS: Record<
  DeploymentStatus,
  {
    Icon: LucideIcon
    label: string
    spin?: boolean
    variant: BadgeProps['variant']
  }
> = {
  failed: { Icon: XCircle, label: 'Failed', variant: 'danger' },
  in_progress: {
    Icon: LoaderCircle,
    label: 'Deploying',
    spin: true,
    variant: 'warning',
  },
  pending: { Icon: Clock, label: 'Queued', variant: 'neutral' },
  rolled_back: { Icon: RotateCcw, label: 'Rolled back', variant: 'warning' },
  success: { Icon: CheckCircle2, label: 'Deployed', variant: 'success' },
}

// Environment fields that are structural (the node itself) or already shown in
// the header row. Everything else on the environment object is a dynamic,
// blueprint-defined ``DEPLOYED_IN`` edge attribute and is surfaced in the grid.
const RESERVED_ENV_KEYS = new Set([
  'can_deploy',
  'can_promote',
  'created_at',
  'description',
  'icon',
  'id',
  'label_color',
  'name',
  'organization',
  'relationships',
  'slug',
  'sort_order',
  'updated_at',
  'url',
  'version',
])

// fallow-ignore-next-line complexity
export function ProjectEnvironmentsCard({
  deploymentStatus,
  environments,
  orgSlug,
  projectId,
  projectSchema,
}: ProjectEnvironmentsCardProps) {
  const attrDefs = useMemo(
    () => environmentAttributeDefs(projectSchema),
    [projectSchema],
  )
  const { patch, pendingKey, replaceAll, replacing } = useEnvironmentEdgePatch(
    orgSlug,
    projectId,
  )
  const { displayNames, loginToEmail } = useLoginToEmail()

  const [adding, setAdding] = useState(false)
  const [pendingDelete, setPendingDelete] = useState<null | string>(null)

  const { data: orgEnvironments = [] } = useQuery({
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
  })

  const unassignedEnvs = useMemo(() => {
    const assigned = new Set(environments.map((e) => e.slug))
    return orgEnvironments
      .filter((e) => !assigned.has(e.slug))
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [orgEnvironments, environments])

  const formAttrDefs = useMemo(
    () =>
      Object.entries(attrDefs).filter(([key, def]) => isDraftField(key, def)),
    [attrDefs],
  )

  const handleAdd = async (slug: string, fields: Record<string, unknown>) => {
    const map = buildEdgeMap(environments)
    map[slug] = fields
    await replaceAll(map)
    setAdding(false)
  }

  const handleRemove = async (slug: string) => {
    setPendingDelete(null)
    const map = buildEdgeMap(environments)
    delete map[slug]
    try {
      await replaceAll(map)
    } catch {
      // replaceAll already surfaced the error.
    }
  }

  const pendingDeleteEnv = environments.find((e) => e.slug === pendingDelete)

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>Environments</CardTitle>
        {!adding && unassignedEnvs.length > 0 && (
          <button
            className="text-secondary hover:bg-secondary hover:text-primary inline-flex items-center gap-1.5 rounded px-2.5 py-1 text-xs transition-colors"
            onClick={() => setAdding(true)}
            type="button"
          >
            <Plus className="size-3" />
            Add environment
          </button>
        )}
      </CardHeader>
      <CardContent>
        {adding && (
          <AddEnvironmentForm
            attrDefs={formAttrDefs}
            onCancel={() => setAdding(false)}
            onSubmit={handleAdd}
            options={unassignedEnvs}
            saving={replacing}
          />
        )}
        {environments.length === 0 && !adding && (
          <p className="text-tertiary text-sm">No environments.</p>
        )}
        <div className="space-y-0">
          {/* fallow-ignore-next-line complexity */}
          {environments.map((env) => {
            const url =
              typeof env.url === 'string' ? sanitizeHttpUrl(env.url) : null
            // Protocol/trailing-slash stripped for a shorter on-screen value.
            const displayUrl = url
              ? url.replace(/^https?:\/\//, '').replace(/\/$/, '')
              : null
            const urlText = (
              <span className="text-primary text-sm">{displayUrl}</span>
            )
            const deployment = deploymentStatus[env.slug]
            const version = deployment
              ? (deployment.tag ?? deployment.committish)
              : null
            const attrs = dynamicAttributes(env)
            const urlDef = attrDefs.url ?? URL_DEF
            const showUrlBlock = isFieldEditable('url', urlDef) || !!displayUrl
            return (
              <div
                className="group border-tertiary border-b py-4 last:border-0"
                key={env.slug}
              >
                <div className="flex items-center gap-x-4 gap-y-2">
                  <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
                    <EnvironmentBadge
                      label_color={env.label_color}
                      name={env.name}
                      slug={env.slug}
                    />
                    {deployment?.status ? (
                      <ReleaseBadge status={deployment.status} />
                    ) : null}
                    {version ? (
                      <span className="text-primary font-mono text-sm tabular-nums">
                        {version}
                      </span>
                    ) : null}
                    {deployment?.updated ? (
                      <span className="text-tertiary text-sm">
                        {deployment.updated}
                      </span>
                    ) : null}
                  </div>

                  {/* URL — pinned to the right of the header line; never wraps
                      (clips before dropping to a new line) with a quick-open
                      link, and inline-editable when the schema allows it. */}
                  {showUrlBlock ? (
                    <div className="ml-auto flex min-w-0 items-center gap-1.5 overflow-hidden pl-4 whitespace-nowrap">
                      {isFieldEditable('url', urlDef) ? (
                        <InlineField
                          def={urlDef}
                          display={urlText}
                          onCommit={(v) => patch(env.slug, 'url', v)}
                          pending={pendingKey === `${env.slug}/url`}
                          raw={env.url ?? null}
                        />
                      ) : (
                        urlText
                      )}
                      {url ? (
                        <a
                          aria-label="Open URL"
                          className="text-warning shrink-0"
                          href={url}
                          rel="noopener noreferrer"
                          target="_blank"
                        >
                          <ExternalLink className="size-3" />
                        </a>
                      ) : null}
                    </div>
                  ) : null}

                  {/* Remove — revealed on row hover (and keyboard focus). */}
                  <button
                    aria-label={`Remove ${env.name} environment`}
                    className={`text-secondary hover:text-danger shrink-0 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100 ${showUrlBlock ? '' : 'ml-auto'}`}
                    disabled={replacing}
                    onClick={() => setPendingDelete(env.slug)}
                    type="button"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>

                {deployment?.performedBy || attrs.length > 0 ? (
                  <div
                    className="mt-4 grid gap-4"
                    style={{
                      gridTemplateColumns:
                        'repeat(auto-fit, minmax(150px, 1fr))',
                    }}
                  >
                    {/* Deployed by — read-only actor identity */}
                    {deployment?.performedBy ? (
                      <div className="min-w-0">
                        <div className={OVERLINE_CLASS}>Deployed by</div>
                        <UserIdentity
                          actor={deployment.performedBy}
                          displayNames={displayNames}
                          email={
                            deployment.performedByEmail ??
                            loginToEmail.get(deployment.performedBy)
                          }
                          size="small"
                        />
                      </div>
                    ) : null}

                    {/* Blueprint edge attributes — inline-editable when the
                        schema marks them editable, else read-only. */}
                    {/* fallow-ignore-next-line complexity */}
                    {attrs.map(({ key, rawValue }) => {
                      const def = attrDefs[key]
                      const display = (
                        <AttributeValue
                          def={def}
                          fallback={
                            <span className="text-tertiary">&mdash;</span>
                          }
                          rawValue={rawValue}
                        />
                      )
                      return (
                        <div className="min-w-0" key={key}>
                          <div className={OVERLINE_CLASS}>
                            {def?.title || formatFieldKey(key)}
                          </div>
                          {def && isFieldEditable(key, def) ? (
                            <InlineField
                              def={def}
                              display={display}
                              onCommit={(v) => patch(env.slug, key, v)}
                              pending={pendingKey === `${env.slug}/${key}`}
                              raw={rawValue}
                            />
                          ) : (
                            display
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>
      </CardContent>

      <ConfirmDialog
        confirmLabel="Remove"
        description="This will remove the environment from the project along with any environment-specific attribute values."
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => {
          if (pendingDelete) void handleRemove(pendingDelete)
        }}
        open={pendingDelete !== null}
        title={
          pendingDeleteEnv
            ? `Remove ${pendingDeleteEnv.name} environment?`
            : 'Remove environment?'
        }
      />
    </Card>
  )
}

// Inline form for attaching an environment to the project: pick an
// unassigned environment, optionally set the URL and any blueprint-defined
// edge attributes. Drafts are discarded on cancel (the parent unmounts it).
function AddEnvironmentForm({
  attrDefs,
  onCancel,
  onSubmit,
  options,
  saving,
}: {
  attrDefs: [string, ProjectSchemaSectionProperty][]
  onCancel: () => void
  onSubmit: (slug: string, fields: Record<string, unknown>) => Promise<void>
  options: { name: string; slug: string }[]
  saving: boolean
}) {
  const [slug, setSlug] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const setDraft = (key: string, value: string) =>
    setDrafts((d) => ({ ...d, [key]: value }))

  const submit = async () => {
    if (!slug) return
    try {
      await onSubmit(slug, coerceDrafts(drafts, Object.fromEntries(attrDefs)))
    } catch {
      // Parent surfaced the error; keep the form open for retry.
    }
  }

  return (
    <div className="border-tertiary mb-4 flex flex-wrap items-end gap-3 border-b pb-4">
      <div className="w-44">
        <div className={OVERLINE_CLASS}>Environment</div>
        <Select onValueChange={setSlug} value={slug}>
          <SelectTrigger className="text-sm">
            <SelectValue placeholder="Select…" />
          </SelectTrigger>
          <SelectContent>
            {options.map((env) => (
              <SelectItem key={env.slug} value={env.slug}>
                {env.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="min-w-56 flex-1">
        <div className={OVERLINE_CLASS}>URL</div>
        <Input
          className="text-sm"
          onChange={(e) => setDraft('url', e.target.value)}
          placeholder="https://…"
          value={drafts.url ?? ''}
        />
      </div>
      {attrDefs.map(([key, def]) => (
        <div className="w-44" key={key}>
          <div className={OVERLINE_CLASS}>
            {def.title || formatFieldKey(key)}
          </div>
          <AttrDraftInput
            def={def}
            label={def.title || formatFieldKey(key)}
            onChange={(v) => setDraft(key, v)}
            value={drafts[key] ?? ''}
          />
        </div>
      ))}
      <div className="flex gap-2">
        <Button
          disabled={!slug || saving}
          onClick={submit}
          size="sm"
          type="button"
        >
          Add
        </Button>
        <Button
          disabled={saving}
          onClick={onCancel}
          size="sm"
          type="button"
          variant="ghost"
        >
          Cancel
        </Button>
      </div>
    </div>
  )
}

// Draft input for one blueprint edge attribute: enum defs render as a
// select, everything else as a text/number input.
// fallow-ignore-next-line complexity
function AttrDraftInput({
  def,
  label,
  onChange,
  value,
}: {
  def: ProjectSchemaSectionProperty
  label: string
  onChange: (value: string) => void
  value: string
}) {
  if (def.enum?.length) {
    return (
      <Select onValueChange={onChange} value={value}>
        <SelectTrigger className="text-sm">
          <SelectValue placeholder="Select…" />
        </SelectTrigger>
        <SelectContent>
          {def.enum.map((option) => (
            <SelectItem key={option} value={option}>
              {option}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }
  return (
    <Input
      className="text-sm"
      onChange={(e) => onChange(e.target.value)}
      placeholder={label}
      type={NUMERIC_TYPES.has(def.type ?? '') ? 'number' : 'text'}
      value={value}
    />
  )
}

const NUMERIC_TYPES = new Set(['integer', 'number'])

// Full slug -> DEPLOYED_IN edge-props map for the project PATCH. Everything on
// the environment object that isn't an Environment node field is a flattened
// edge property and must round-trip through the wholesale edge replace.
function buildEdgeMap(
  environments: Environment[],
): Record<string, Record<string, unknown>> {
  const map: Record<string, Record<string, unknown>> = {}
  for (const env of environments) {
    map[env.slug] = Object.fromEntries(
      Object.entries(env).filter(
        ([key, value]) =>
          !ENVIRONMENT_BASE_FIELDS_SET.has(key) && value != null,
      ),
    )
  }
  return map
}

// Convert the form's non-empty draft strings into typed edge-prop values.
// fallow-ignore-next-line complexity
function coerceDrafts(
  drafts: Record<string, string>,
  defs: Record<string, ProjectSchemaSectionProperty>,
): Record<string, unknown> {
  const fields: Record<string, unknown> = {}
  for (const [key, raw] of Object.entries(drafts)) {
    const value = raw.trim()
    if (!value) continue
    fields[key] = NUMERIC_TYPES.has(defs[key]?.type ?? '')
      ? Number(value)
      : value
  }
  return fields
}

// Blueprint-defined edge attributes for a single environment, ordered
// deterministically by key. Membership is dynamic — whatever the project's
// relationship blueprint declares flows through here, no hard-coded columns.
// Raw values are returned as-is; ``AttributeValue`` applies the shared
// formatting + x-ui display logic using the matching schema def.
function dynamicAttributes(
  env: Environment,
): { key: string; rawValue: unknown }[] {
  const record = env as Record<string, unknown>
  return Object.keys(record)
    .filter((key) => !RESERVED_ENV_KEYS.has(key))
    .sort()
    .map((key) => ({ key, rawValue: record[key] }))
}

// Merge the property defs from every ``environment``-scoped schema section
// into a flat key→def lookup for the edge attributes.
// fallow-ignore-next-line complexity
function environmentAttributeDefs(
  schema?: ProjectSchemaResponse,
): Record<string, ProjectSchemaSectionProperty> {
  const defs: Record<string, ProjectSchemaSectionProperty> = {}
  if (!schema) return defs
  for (const section of schema.sections) {
    if (section.scope !== 'environment') continue
    for (const [key, def] of Object.entries(section.properties)) {
      defs[key] ??= def
    }
  }
  return defs
}

// Add-form eligibility for a blueprint edge attribute: editable per the
// shared policy and representable as a simple text/number/enum input.
// Anything else stays inline-editable on the row after the environment is
// added. URL is excluded because the form has a dedicated URL input.
// fallow-ignore-next-line complexity
function isDraftField(key: string, def: ProjectSchemaSectionProperty): boolean {
  const simple =
    Boolean(def.enum?.length) ||
    def.type === 'string' ||
    NUMERIC_TYPES.has(def.type ?? '')
  return key !== 'url' && simple && isFieldEditable(key, def)
}

function ReleaseBadge({ status }: { status: string }) {
  const meta = RELEASE_STATUS[status as DeploymentStatus]
  if (!meta) return null
  const { Icon, label, spin, variant } = meta
  return (
    <Badge className="gap-1" variant={variant}>
      <Icon className={`size-3${spin ? ' animate-spin' : ''}`} />
      {label}
    </Badge>
  )
}
