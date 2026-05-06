import { useState } from 'react'

import {
  ArrowLeft,
  Edit2,
  ExternalLink,
  Info,
  Key,
  type LucideIcon,
  Puzzle,
  Webhook,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useOrganization } from '@/contexts/OrganizationContext'
import { statusBadgeVariant } from '@/lib/status-colors'
import type { ThirdPartyService } from '@/types'

import { OAuth2ApplicationList } from './OAuth2ApplicationList'
import { ServicePluginList } from './ServicePluginList'
import { ServiceWebhookList } from './ServiceWebhookList'

type DetailTab = 'applications' | 'details' | 'plugins' | 'webhooks'

interface ThirdPartyServiceDetailProps {
  onBack: () => void
  onEdit: () => void
  service: ThirdPartyService
}

export function ThirdPartyServiceDetail({
  onBack,
  onEdit,
  service,
}: ThirdPartyServiceDetailProps) {
  const { selectedOrganization } = useOrganization()
  const [activeTab, setActiveTab] = useState<DetailTab>('details')
  const [webhookDetailActive, setWebhookDetailActive] = useState(false)
  const [appDetailActive, setAppDetailActive] = useState(false)
  const [pluginConfigActive, setPluginConfigActive] = useState(false)
  const statusVariant = statusBadgeVariant(service.status)
  const linkEntries = Object.entries(service.links || {})
  const identifierEntries = Object.entries(service.identifiers || {})
  const hasOAuthConfig =
    service.api_endpoint ||
    service.authorization_endpoint ||
    service.token_endpoint ||
    service.revoke_endpoint ||
    service.use_pkce != null

  const tabs: { icon: LucideIcon; id: DetailTab; label: string }[] = [
    { icon: Info, id: 'details', label: 'Details' },
    { icon: Key, id: 'applications', label: 'Applications' },
    { icon: Puzzle, id: 'plugins', label: 'Plugins' },
    { icon: Webhook, id: 'webhooks', label: 'Webhooks' },
  ]

  return (
    <div className="space-y-6">
      {/* Header - hidden when viewing webhook detail to avoid double Back buttons */}
      {!webhookDetailActive && !appDetailActive && (
        <>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button onClick={onBack} variant="outline">
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back
              </Button>
              <div>
                <div className="flex items-center gap-3">
                  {service.icon && (
                    <EntityIcon
                      className="h-8 w-8 rounded object-cover"
                      icon={service.icon}
                    />
                  )}
                  <CardTitle>{service.name}</CardTitle>
                  <Badge variant={statusVariant}>{service.status}</Badge>
                </div>
                {service.description && (
                  <p className="mt-1 text-sm text-secondary">
                    {service.description}
                  </p>
                )}
              </div>
            </div>
            {!pluginConfigActive && (
              <Button
                className="bg-action text-action-foreground hover:bg-action-hover"
                onClick={onEdit}
              >
                <Edit2 className="mr-2 h-4 w-4" />
                Edit Service
              </Button>
            )}
          </div>

          {/* Tabs */}
          <div className="border-b border-tertiary">
            <div className="flex gap-0">
              {tabs.map((tab) => {
                const Icon = tab.icon
                const isActive = activeTab === tab.id
                return (
                  <button
                    className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                      isActive
                        ? 'border-info text-info'
                        : 'border-transparent text-secondary hover:text-primary'
                    }`}
                    key={tab.id}
                    onClick={() => {
                      if (tab.id !== 'plugins') setPluginConfigActive(false)
                      setActiveTab(tab.id)
                    }}
                  >
                    <Icon className="h-4 w-4" />
                    {tab.label}
                  </button>
                )
              })}
            </div>
          </div>
        </>
      )}

      {/* Details Tab */}
      {activeTab === 'details' && (
        <div className="space-y-6">
          {/* Service Info */}
          <Card>
            <CardContent className="p-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <div className="text-sm text-secondary">Slug</div>
                  <div className="mt-1 text-primary">
                    <code className="rounded bg-secondary px-2 py-1 text-sm text-primary">
                      {service.slug}
                    </code>
                  </div>
                </div>
                <div>
                  <div className="text-sm text-secondary">Vendor</div>
                  <div className="mt-1 text-primary">{service.vendor}</div>
                </div>
                <div>
                  <div className="text-sm text-secondary">Organization</div>
                  <div className="mt-1 text-primary">
                    {(service.organization?.name as string | undefined) || (
                      <span className="text-tertiary">Not assigned</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-secondary">Managing Team</div>
                  <div className="mt-1 text-primary">
                    {(service.team?.name as string | undefined) || (
                      <span className="text-tertiary">Not assigned</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-secondary">Category</div>
                  <div className="mt-1 text-primary">
                    {service.category || (
                      <span className="text-tertiary">Not set</span>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-sm text-secondary">Service URL</div>
                  <div className="mt-1">
                    {service.service_url ? (
                      isSafeUrl(service.service_url) ? (
                        <a
                          className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                          href={service.service_url}
                          rel="noopener noreferrer"
                          target="_blank"
                        >
                          {service.service_url}
                          <ExternalLink className="h-3 w-3" />
                        </a>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-sm">
                          {service.service_url}
                        </span>
                      )
                    ) : (
                      <span className="text-tertiary">Not set</span>
                    )}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* OAuth 2.0 Configuration */}
          {hasOAuthConfig && (
            <Card>
              <CardHeader className="px-6 pb-0 pt-5">
                <CardTitle>OAuth 2.0 Configuration</CardTitle>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
                  {service.api_endpoint && (
                    <div>
                      <div className="text-sm text-secondary">API Endpoint</div>
                      <div className="mt-1">
                        {isSafeUrl(service.api_endpoint) ? (
                          <a
                            className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                            href={service.api_endpoint}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            {service.api_endpoint}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-sm">
                            {service.api_endpoint}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {service.authorization_endpoint && (
                    <div>
                      <div className="text-sm text-secondary">
                        Authorization Endpoint
                      </div>
                      <div className="mt-1">
                        {isSafeUrl(service.authorization_endpoint) ? (
                          <a
                            className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                            href={service.authorization_endpoint}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            {service.authorization_endpoint}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-sm">
                            {service.authorization_endpoint}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {service.token_endpoint && (
                    <div>
                      <div className="text-sm text-secondary">
                        Token Endpoint
                      </div>
                      <div className="mt-1">
                        {isSafeUrl(service.token_endpoint) ? (
                          <a
                            className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                            href={service.token_endpoint}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            {service.token_endpoint}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-sm">
                            {service.token_endpoint}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {service.revoke_endpoint && (
                    <div>
                      <div className="text-sm text-secondary">
                        Revoke Endpoint
                      </div>
                      <div className="mt-1">
                        {isSafeUrl(service.revoke_endpoint) ? (
                          <a
                            className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                            href={service.revoke_endpoint}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            {service.revoke_endpoint}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-sm">
                            {service.revoke_endpoint}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                  {service.use_pkce != null && (
                    <div>
                      <div className="text-sm text-secondary">Use PKCE</div>
                      <div className="mt-1 text-primary">
                        {service.use_pkce ? 'Yes' : 'No'}
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Links */}
          {linkEntries.length > 0 && (
            <Card>
              <CardHeader className="px-6 pb-0 pt-5">
                <CardTitle>Links</CardTitle>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                  {linkEntries.map(([label, url]) => (
                    <div key={label}>
                      <div className="text-sm text-secondary">{label}</div>
                      <div className="mt-1">
                        {isSafeUrl(String(url)) ? (
                          <a
                            className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                            href={String(url)}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            {String(url)}
                            <ExternalLink className="h-3 w-3" />
                          </a>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-sm">
                            {String(url)}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Identifiers */}
          {identifierEntries.length > 0 && (
            <Card>
              <CardHeader className="px-6 pb-0 pt-5">
                <CardTitle>Identifiers</CardTitle>
              </CardHeader>
              <CardContent className="p-6">
                <div className="grid grid-cols-2 gap-4">
                  {identifierEntries.map(([label, val]) => (
                    <div key={label}>
                      <div className="text-sm text-secondary">{label}</div>
                      <div className="mt-1 text-primary">
                        <code className="rounded bg-secondary px-2 py-1 text-sm text-primary">
                          {String(val)}
                        </code>
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Applications Tab */}
      {activeTab === 'applications' && (
        <OAuth2ApplicationList
          onViewModeChange={(mode) =>
            setAppDetailActive(mode === 'create' || mode === 'edit')
          }
          orgSlug={selectedOrganization?.slug || ''}
          serviceSlug={service.slug}
        />
      )}

      {/* Plugins Tab */}
      {activeTab === 'plugins' && (
        <ServicePluginList
          onViewModeChange={(mode) =>
            setPluginConfigActive(mode === 'configure')
          }
          orgSlug={selectedOrganization?.slug || ''}
          serviceSlug={service.slug}
        />
      )}

      {/* Webhooks Tab */}
      {activeTab === 'webhooks' && (
        <ServiceWebhookList
          onViewModeChange={(mode) =>
            setWebhookDetailActive(mode === 'detail' || mode === 'edit')
          }
          orgSlug={selectedOrganization?.slug || ''}
          serviceSlug={service.slug}
        />
      )}
    </div>
  )
}

function isSafeUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url)
    return protocol === 'http:' || protocol === 'https:'
  } catch {
    return false
  }
}
