import { useState } from 'react'
import {
  ArrowLeft,
  Edit2,
  ExternalLink,
  Info,
  Key,
  Webhook,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { OAuth2ApplicationList } from './OAuth2ApplicationList'
import { ServiceWebhookList } from './ServiceWebhookList'
import { useOrganization } from '@/contexts/OrganizationContext'
import { EntityIcon } from '@/components/ui/entity-icon'
import { statusBadgeVariant } from '@/lib/status-colors'
import { Badge } from '@/components/ui/badge'
import type { ThirdPartyService } from '@/types'

interface ThirdPartyServiceDetailProps {
  service: ThirdPartyService
  onEdit: () => void
  onBack: () => void
}

type DetailTab = 'details' | 'applications' | 'webhooks'

export function ThirdPartyServiceDetail({
  service,
  onEdit,
  onBack,
}: ThirdPartyServiceDetailProps) {
  const { selectedOrganization } = useOrganization()
  const [activeTab, setActiveTab] = useState<DetailTab>('details')
  const [webhookDetailActive, setWebhookDetailActive] = useState(false)
  const [appDetailActive, setAppDetailActive] = useState(false)
  const statusVariant = statusBadgeVariant(service.status)
  const linkEntries = Object.entries(service.links || {})
  const identifierEntries = Object.entries(service.identifiers || {})

  const tabs: { id: DetailTab; label: string; icon: typeof Info }[] = [
    { id: 'details', label: 'Details', icon: Info },
    { id: 'applications', label: 'Applications', icon: Key },
    { id: 'webhooks', label: 'Webhooks', icon: Webhook },
  ]

  return (
    <div className="space-y-6">
      {/* Header - hidden when viewing webhook detail to avoid double Back buttons */}
      {!webhookDetailActive && !appDetailActive && (
        <>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="outline" onClick={onBack}>
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back
              </Button>
              <div>
                <div className="flex items-center gap-3">
                  {service.icon && (
                    <EntityIcon
                      icon={service.icon}
                      className="h-8 w-8 rounded object-cover"
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
            <Button
              onClick={onEdit}
              className="bg-action text-action-foreground hover:bg-action-hover"
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit Service
            </Button>
          </div>

          {/* Tabs */}
          <div className="border-b border-tertiary">
            <div className="flex gap-0">
              {tabs.map((tab) => {
                const Icon = tab.icon
                const isActive = activeTab === tab.id
                return (
                  <button
                    key={tab.id}
                    onClick={() => setActiveTab(tab.id)}
                    className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors ${
                      isActive
                        ? 'border-info text-info'
                        : 'border-transparent text-secondary hover:text-primary'
                    }`}
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
                      <a
                        href={service.service_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                      >
                        {service.service_url}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    ) : (
                      <span className="text-tertiary">Not set</span>
                    )}
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

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
                        <a
                          href={String(url)}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="hover:text-info/80 inline-flex items-center gap-1 text-sm text-info"
                        >
                          {String(url)}
                          <ExternalLink className="h-3 w-3" />
                        </a>
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
          orgSlug={selectedOrganization?.slug || ''}
          serviceSlug={service.slug}
          onViewModeChange={(mode) =>
            setAppDetailActive(mode === 'create' || mode === 'edit')
          }
        />
      )}

      {/* Webhooks Tab */}
      {activeTab === 'webhooks' && (
        <ServiceWebhookList
          orgSlug={selectedOrganization?.slug || ''}
          serviceSlug={service.slug}
          onViewModeChange={(mode) =>
            setWebhookDetailActive(mode === 'detail' || mode === 'edit')
          }
        />
      )}
    </div>
  )
}
