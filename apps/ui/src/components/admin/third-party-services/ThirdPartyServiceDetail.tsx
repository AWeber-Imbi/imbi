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
import { OAuth2ApplicationList } from './OAuth2ApplicationList'
import { ServiceWebhookList } from './ServiceWebhookList'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { ThirdPartyService } from '@/types'

interface ThirdPartyServiceDetailProps {
  service: ThirdPartyService
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

type DetailTab = 'details' | 'applications' | 'webhooks'

const STATUS_COLORS: Record<
  string,
  { bg: string; text: string; darkBg: string; darkText: string }
> = {
  active: {
    bg: 'bg-green-100',
    text: 'text-green-700',
    darkBg: 'bg-green-900/30',
    darkText: 'text-green-400',
  },
  deprecated: {
    bg: 'bg-yellow-100',
    text: 'text-yellow-700',
    darkBg: 'bg-yellow-900/30',
    darkText: 'text-yellow-400',
  },
  evaluating: {
    bg: 'bg-blue-100',
    text: 'text-blue-700',
    darkBg: 'bg-blue-900/30',
    darkText: 'text-blue-400',
  },
  inactive: {
    bg: 'bg-gray-100',
    text: 'text-gray-700',
    darkBg: 'bg-gray-700',
    darkText: 'text-gray-400',
  },
}

export function ThirdPartyServiceDetail({
  service,
  onEdit,
  onBack,
  isDarkMode,
}: ThirdPartyServiceDetailProps) {
  const { selectedOrganization } = useOrganization()
  const [activeTab, setActiveTab] = useState<DetailTab>('details')
  const [webhookDetailActive, setWebhookDetailActive] = useState(false)
  const [appDetailActive, setAppDetailActive] = useState(false)
  const statusColor = STATUS_COLORS[service.status] || STATUS_COLORS.inactive
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
              <Button
                variant="outline"
                onClick={onBack}
                className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
              >
                <ArrowLeft className="mr-2 h-4 w-4" />
                Back
              </Button>
              <div>
                <div className="flex items-center gap-3">
                  {service.icon && (
                    <img
                      src={service.icon}
                      alt=""
                      className="rounded h-8 w-8 object-cover"
                    />
                  )}
                  <h2
                    className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                  >
                    {service.name}
                  </h2>
                  <span
                    className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      isDarkMode
                        ? `${statusColor.darkBg} ${statusColor.darkText}`
                        : `${statusColor.bg} ${statusColor.text}`
                    }`}
                  >
                    {service.status}
                  </span>
                </div>
                {service.description && (
                  <p
                    className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    {service.description}
                  </p>
                )}
              </div>
            </div>
            <Button
              onClick={onEdit}
              className="bg-[#2A4DD0] text-white hover:bg-blue-700"
            >
              <Edit2 className="mr-2 h-4 w-4" />
              Edit Service
            </Button>
          </div>

          {/* Tabs */}
          <div
            className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
          >
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
                        ? isDarkMode
                          ? 'border-blue-400 text-blue-400'
                          : 'border-[#2A4DD0] text-[#2A4DD0]'
                        : isDarkMode
                          ? 'border-transparent text-gray-400 hover:text-gray-200'
                          : 'border-transparent text-gray-600 hover:text-gray-900'
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
          <div
            className={`rounded-lg border p-6 ${
              isDarkMode
                ? 'border-gray-700 bg-gray-800'
                : 'border-gray-200 bg-white'
            }`}
          >
            <div className="grid grid-cols-2 gap-6">
              <div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Slug
                </div>
                <div
                  className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  <code
                    className={`rounded px-2 py-1 text-sm ${
                      isDarkMode
                        ? 'bg-gray-700 text-gray-300'
                        : 'bg-gray-100 text-gray-700'
                    }`}
                  >
                    {service.slug}
                  </code>
                </div>
              </div>
              <div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Vendor
                </div>
                <div
                  className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {service.vendor}
                </div>
              </div>
              <div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Organization
                </div>
                <div
                  className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {service.organization.name}
                </div>
              </div>
              <div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Managing Team
                </div>
                <div
                  className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {service.team?.name || (
                    <span
                      className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}
                    >
                      Not assigned
                    </span>
                  )}
                </div>
              </div>
              <div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Category
                </div>
                <div
                  className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                >
                  {service.category || (
                    <span
                      className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}
                    >
                      Not set
                    </span>
                  )}
                </div>
              </div>
              <div>
                <div
                  className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Service URL
                </div>
                <div className="mt-1">
                  {service.service_url ? (
                    <a
                      href={service.service_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={`inline-flex items-center gap-1 text-sm ${
                        isDarkMode
                          ? 'text-blue-400 hover:text-blue-300'
                          : 'text-blue-600 hover:text-blue-700'
                      }`}
                    >
                      {service.service_url}
                      <ExternalLink className="h-3 w-3" />
                    </a>
                  ) : (
                    <span
                      className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}
                    >
                      Not set
                    </span>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Links */}
          {linkEntries.length > 0 && (
            <div
              className={`rounded-lg border p-6 ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <h3
                className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                Links
              </h3>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                {linkEntries.map(([label, url]) => (
                  <div key={label}>
                    <div
                      className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                    >
                      {label}
                    </div>
                    <div className="mt-1">
                      <a
                        href={String(url)}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`inline-flex items-center gap-1 text-sm ${
                          isDarkMode
                            ? 'text-blue-400 hover:text-blue-300'
                            : 'text-blue-600 hover:text-blue-700'
                        }`}
                      >
                        {String(url)}
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Identifiers */}
          {identifierEntries.length > 0 && (
            <div
              className={`rounded-lg border p-6 ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <h3
                className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                Identifiers
              </h3>
              <div className="grid grid-cols-2 gap-4">
                {identifierEntries.map(([label, val]) => (
                  <div key={label}>
                    <div
                      className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                    >
                      {label}
                    </div>
                    <div
                      className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                    >
                      <code
                        className={`rounded px-2 py-1 text-sm ${
                          isDarkMode
                            ? 'bg-gray-700 text-gray-300'
                            : 'bg-gray-100 text-gray-700'
                        }`}
                      >
                        {String(val)}
                      </code>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Applications Tab */}
      {activeTab === 'applications' && (
        <OAuth2ApplicationList
          orgSlug={selectedOrganization?.slug || ''}
          serviceSlug={service.slug}
          isDarkMode={isDarkMode}
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
          isDarkMode={isDarkMode}
          onViewModeChange={(mode) =>
            setWebhookDetailActive(mode === 'detail' || mode === 'edit')
          }
        />
      )}
    </div>
  )
}
