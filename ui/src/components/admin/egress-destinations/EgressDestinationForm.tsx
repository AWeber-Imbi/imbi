import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listEgressDestinationChanges } from '@/api/endpoints'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { formatRelativeDate } from '@/lib/formatDate'
import { queryKeys } from '@/lib/queryKeys'
import { slugify } from '@/lib/utils'
import type { EgressDestination, EgressDestinationCreate } from '@/types'

import { FormHeader } from '../form-header'
import { formatPorts, parsePorts } from './ports'

interface EgressDestinationFormProps {
  destination: EgressDestination | null
  error?: unknown
  isLoading: boolean
  onCancel: () => void
  onSave: (body: EgressDestinationCreate) => void
}

/** A DNS label, as the API accepts it. */
const SLUG = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/

/**
 * Create or edit an egress destination. The API checks the CIDRs
 * (internal ranges, no loopback or link-local) and the port limits.
 */
// fallow-ignore-next-line complexity
export function EgressDestinationForm({
  destination,
  error,
  isLoading,
  onCancel,
  onSave,
}: EgressDestinationFormProps) {
  const isEditing = !!destination
  const { organizations } = useOrganization()
  const [name, setName] = useState(destination?.name ?? '')
  const [slug, setSlug] = useState(destination?.slug ?? '')
  const [description, setDescription] = useState(destination?.description ?? '')
  const [cidrs, setCidrs] = useState((destination?.cidrs ?? []).join('\n'))
  const [ports, setPorts] = useState(formatPorts(destination?.ports ?? []))
  const [global, setGlobal] = useState(destination?.global ?? false)
  const [orgs, setOrgs] = useState<string[]>(destination?.organizations ?? [])
  const [errors, setErrors] = useState<Record<string, string>>({})

  const handleSave = () => {
    const parsedPorts = parsePorts(ports)
    const next: Record<string, string> = {}
    if (!name.trim()) next.name = 'Name is required'
    if (!SLUG.test(slug)) {
      next.slug =
        'Lowercase letters, numbers, and hyphens; starts and ends with a letter or number'
    }
    if (parseList(cidrs).length === 0) next.cidrs = 'Add at least one CIDR'
    if (!parsedPorts?.length) {
      next.ports = 'Add ports such as 443 or 53/udp, from 1 to 65535'
    }
    setErrors(next)
    if (Object.keys(next).length || !parsedPorts) return
    onSave({
      cidrs: parseList(cidrs),
      description: description.trim() || null,
      global,
      name: name.trim(),
      organizations: global ? [] : orgs,
      ports: parsedPorts,
      slug,
    })
  }

  return (
    <div className="space-y-6">
      <FormHeader
        createLabel="Create Destination"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        title={
          isEditing ? `Edit ${destination.name}` : 'New egress destination'
        }
      />
      {!!error && (
        <ErrorBanner error={error} title="Failed to save the destination" />
      )}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FormField
              error={errors.name}
              htmlFor="egress-name"
              label="Name"
              required
              touched
            >
              <Input
                id="egress-name"
                onChange={(e) => {
                  setName(e.target.value)
                  if (!isEditing) setSlug(slugify(e.target.value))
                }}
                value={name}
              />
            </FormField>
            <FormField
              error={errors.slug}
              htmlFor="egress-slug"
              label="Slug"
              required
              touched
            >
              <Input
                disabled={isEditing}
                id="egress-slug"
                onChange={(e) => setSlug(e.target.value)}
                value={slug}
              />
            </FormField>
          </div>
          <FormField htmlFor="egress-description" label="Description">
            <Textarea
              id="egress-description"
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              value={description}
            />
          </FormField>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FormField
              description="IPv4 CIDRs, one per line. A change starts a new generation."
              error={errors.cidrs}
              htmlFor="egress-cidrs"
              label="CIDRs"
              required
              touched
            >
              <Textarea
                className="font-mono"
                id="egress-cidrs"
                onChange={(e) => setCidrs(e.target.value)}
                placeholder="10.20.0.0/16"
                rows={4}
                value={cidrs}
              />
            </FormField>
            <FormField
              description="Separate with commas. TCP when no protocol is given."
              error={errors.ports}
              htmlFor="egress-ports"
              label="Ports"
              required
              touched
            >
              <Input
                className="font-mono"
                id="egress-ports"
                onChange={(e) => setPorts(e.target.value)}
                placeholder="443, 5432/tcp, 53/udp"
                value={ports}
              />
            </FormField>
          </div>
          <div className="border-input flex items-start justify-between gap-3 rounded-lg border p-3">
            <div>
              <Label className="text-sm font-medium" htmlFor="egress-global">
                Global
              </Label>
              <p className="text-tertiary text-xs">
                Every chain gets this destination. Agents cannot select it.
              </p>
            </div>
            <Switch
              checked={global}
              id="egress-global"
              onCheckedChange={setGlobal}
            />
          </div>
          {!global && (
            <fieldset>
              <legend className="text-secondary mb-1.5 text-sm">
                Organizations
              </legend>
              <p className="text-tertiary mb-2 text-xs">
                The organizations whose agents may select it. None selected
                means all.
              </p>
              <div className="flex flex-wrap gap-x-6 gap-y-2">
                {organizations.map((org) => (
                  <label
                    className="flex items-center gap-2 text-sm"
                    key={org.slug}
                  >
                    <Checkbox
                      checked={orgs.includes(org.slug)}
                      onCheckedChange={(on) =>
                        setOrgs(
                          on
                            ? [...orgs, org.slug]
                            : orgs.filter((o) => o !== org.slug),
                        )
                      }
                    />
                    {org.name}
                  </label>
                ))}
              </div>
            </fieldset>
          )}
        </CardContent>
      </Card>
      {destination && <ChangeHistory slug={destination.slug} />}
    </div>
  )
}

function ChangeHistory({ slug }: { slug: string }) {
  const changes = useQuery({
    queryFn: ({ signal }) => listEgressDestinationChanges(slug, signal),
    queryKey: queryKeys.egressDestinationChanges(slug),
  })
  return (
    <Card>
      <CardContent className="pt-6">
        <h3 className="text-primary mb-3 text-sm font-medium">
          Change history
        </h3>
        {changes.error ? (
          <ErrorBanner error={changes.error} title="Failed to load changes" />
        ) : !changes.data ? (
          <p className="text-tertiary text-sm">Loading…</p>
        ) : changes.data.length === 0 ? (
          <p className="text-tertiary text-sm">No changes.</p>
        ) : (
          <ul className="divide-tertiary divide-y text-sm">
            {changes.data.map((change, i) => (
              <li className="flex gap-4 py-1.5" key={i}>
                <span className="w-20 font-mono text-xs">{change.action}</span>
                <span className="text-secondary flex-1">{change.actor}</span>
                <span className="text-tertiary text-xs">
                  {formatRelativeDate(change.created_at)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

function parseList(value: string): string[] {
  return value.split(/[\s,]+/).filter(Boolean)
}
