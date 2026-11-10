import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listEgressDestinationChanges } from '@/api/endpoints'
import { Card, CardContent } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
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

/** The only ports of a host name destination: the proxy tunnels HTTPS. */
const HOSTNAME_PORTS: EgressDestinationCreate['ports'] = [
  { port: 443, protocol: 'TCP' },
]

const MAX_HOSTNAMES = 25

type Kind = 'cidrs' | 'hostnames'

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
  const [kind, setKind] = useState<Kind>(
    destination?.hostnames?.length ? 'hostnames' : 'cidrs',
  )
  const [cidrs, setCidrs] = useState((destination?.cidrs ?? []).join('\n'))
  const [hostnames, setHostnames] = useState(
    (destination?.hostnames ?? []).join('\n'),
  )
  const [ports, setPorts] = useState(formatPorts(destination?.ports ?? []))
  const [global, setGlobal] = useState(destination?.global ?? false)
  const [orgs, setOrgs] = useState<string[]>(destination?.organizations ?? [])
  const [errors, setErrors] = useState<Record<string, string>>({})

  const isHosts = kind === 'hostnames'
  const target = isHosts
    ? {
        description: 'DNS names, one per line. The API checks them.',
        id: 'egress-hostnames',
        label: 'Host names',
        onChange: setHostnames,
        placeholder: 'api.example.com',
        value: hostnames,
      }
    : {
        description: 'IPv4 CIDRs, one per line.',
        id: 'egress-cidrs',
        label: 'CIDRs',
        onChange: setCidrs,
        placeholder: '10.20.0.0/16',
        value: cidrs,
      }

  const handleSave = () => {
    const parsedPorts = isHosts ? HOSTNAME_PORTS : parsePorts(ports)
    const hosts = parseList(hostnames).map((h) => h.toLowerCase())
    const next: Record<string, string> = {}
    if (!name.trim()) next.name = 'Name is required'
    if (!SLUG.test(slug)) {
      next.slug =
        'Lowercase letters, numbers, and hyphens; starts and ends with a letter or number'
    }
    if (parseList(target.value).length === 0) {
      next.target = `Add at least one ${isHosts ? 'host name' : 'CIDR'}`
    } else if (isHosts && hosts.length > MAX_HOSTNAMES) {
      next.target = `Add at most ${MAX_HOSTNAMES} host names`
    }
    if (!parsedPorts?.length) {
      next.ports = 'Add ports such as 443 or 53/udp, from 1 to 65535'
    }
    setErrors(next)
    if (Object.keys(next).length || !parsedPorts) return
    onSave({
      cidrs: isHosts ? [] : parseList(cidrs),
      description: description.trim() || null,
      global,
      hostnames: isHosts ? hosts : [],
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
          <div className="space-y-2">
            <SegmentedControl
              ariaLabel="Destination kind"
              onValueChange={(v) => setKind(v as Kind)}
              value={kind}
            >
              <SegmentedControlItem disabled={isEditing} value="cidrs">
                CIDRs
              </SegmentedControlItem>
              <SegmentedControlItem disabled={isEditing} value="hostnames">
                Host names
              </SegmentedControlItem>
            </SegmentedControl>
            {isHosts && (
              <p className="text-tertiary text-xs">
                A host name destination works only for HTTPS clients that use
                the egress proxy. The DNS owner of each name controls the
                address that it goes to.
              </p>
            )}
          </div>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <FormField
              description={`${target.description} A change starts a new generation.`}
              error={errors.target}
              htmlFor={target.id}
              label={target.label}
              required
              touched
            >
              <Textarea
                className="font-mono"
                id={target.id}
                onChange={(e) => target.onChange(e.target.value)}
                placeholder={target.placeholder}
                rows={4}
                value={target.value}
              />
            </FormField>
            <FormField
              description={
                isHosts
                  ? 'Host names always use 443/TCP.'
                  : 'Separate with commas. TCP when no protocol is given.'
              }
              error={errors.ports}
              htmlFor="egress-ports"
              label="Ports"
              required
              touched
            >
              <Input
                className="font-mono"
                disabled={isHosts}
                id="egress-ports"
                onChange={(e) => setPorts(e.target.value)}
                placeholder="443, 5432/tcp, 53/udp"
                value={isHosts ? formatPorts(HOSTNAME_PORTS) : ports}
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
