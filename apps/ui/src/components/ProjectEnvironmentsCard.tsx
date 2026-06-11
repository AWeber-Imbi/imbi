import { useMemo } from 'react'

import {
  CheckCircle2,
  Clock,
  ExternalLink,
  LoaderCircle,
  type LucideIcon,
  RotateCcw,
  XCircle,
} from 'lucide-react'

import type {
  ProjectSchemaResponse,
  ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import { AttributeValue } from '@/components/ui/attribute-value'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { isFieldEditable } from '@/components/ui/inline-edit/field-policy'
import { InlineField } from '@/components/ui/inline-edit/InlineField'
import { UserIdentity } from '@/components/ui/user-identity'
import { useEnvironmentEdgePatch } from '@/hooks/useEnvironmentEdgePatch'
import { useLoginToEmail } from '@/hooks/useLoginToEmail'
import { formatFieldKey } from '@/lib/project-field-formatting'
import { sanitizeHttpUrl } from '@/lib/utils'
import type { DeploymentStatus, Project } from '@/types'

interface DeploymentInfo {
  committish: string
  // Deployer of the latest deploy event (remote actor); null for in-product.
  performedBy: null | string
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
  const { patch, pendingKey } = useEnvironmentEdgePatch(orgSlug, projectId)
  const { displayNames, loginToEmail } = useLoginToEmail()
  return (
    <Card>
      <CardHeader>
        <CardTitle>Environments</CardTitle>
      </CardHeader>
      <CardContent>
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
            return (
              <div
                className="border-tertiary border-b py-4 last:border-0"
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
                  {isFieldEditable('url', urlDef) || displayUrl ? (
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
                          email={loginToEmail.get(deployment.performedBy)}
                          size="small"
                        />
                      </div>
                    ) : null}

                    {/* Blueprint edge attributes — inline-editable when the
                        schema marks them editable, else read-only. */}
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
    </Card>
  )
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
