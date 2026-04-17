import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, User, Bell, Key, Shield, Link2, Book } from 'lucide-react'
import { Button } from './ui/button'
import { Card } from './ui/card'
import { SettingsAccount } from './settings/SettingsAccount'
import { SettingsIntegrations } from './settings/SettingsIntegrations'
import { SettingsNotifications } from './settings/SettingsNotifications'
import { SettingsApiKeys } from './settings/SettingsApiKeys'
import { SettingsSecurity } from './settings/SettingsSecurity'

type SettingsTab =
  | 'account'
  | 'integrations'
  | 'notifications'
  | 'api-keys'
  | 'security'
  | 'project-types'

const tabs: { id: SettingsTab; label: string; icon: typeof User }[] = [
  { id: 'account', label: 'Account', icon: User },
  { id: 'integrations', label: 'Integrations', icon: Link2 },
  { id: 'notifications', label: 'Notifications', icon: Bell },
  { id: 'api-keys', label: 'API Keys', icon: Key },
  { id: 'security', label: 'Security', icon: Shield },
  { id: 'project-types', label: 'Project Types', icon: Book },
]

export function Settings() {
  const navigate = useNavigate()
  const { tab } = useParams<{ tab?: string }>()
  const activeTab: SettingsTab = (tab as SettingsTab) || 'account'

  const handleTabChange = (tabId: SettingsTab) => {
    navigate(`/settings/${tabId}`, { replace: true })
  }

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-7">
      {/* Back button */}
      <Button
        variant="ghost"
        onClick={() => navigate(-1)}
        className={'mb-6 gap-2 text-secondary hover:bg-secondary'}
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </Button>

      {/* Header */}
      <div className="mb-8">
        <h1 className={'text-[22px] font-medium text-primary'}>Settings</h1>
        <p className={'mt-1 text-[13px] text-tertiary'}>
          Manage your account preferences and integrations
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* Sidebar navigation */}
        <div className="lg:col-span-1">
          <Card className={'p-2'} style={{ borderWidth: '0.5px' }}>
            <nav className="space-y-1">
              {tabs.map((t) => {
                const Icon = t.icon
                return (
                  <button
                    key={t.id}
                    onClick={() => handleTabChange(t.id)}
                    className={`flex w-full items-center gap-3 rounded-lg px-4 py-3 text-[13.5px] transition-colors ${
                      activeTab === t.id
                        ? 'bg-warning text-warning'
                        : 'text-secondary hover:bg-secondary'
                    }`}
                  >
                    <Icon className="h-[18px] w-[18px]" />
                    <span>{t.label}</span>
                  </button>
                )
              })}
            </nav>
          </Card>
        </div>

        {/* Content area */}
        <div className="lg:col-span-3">
          {activeTab === 'account' && <SettingsAccount />}
          {activeTab === 'integrations' && <SettingsIntegrations />}
          {activeTab === 'notifications' && <SettingsNotifications />}
          {activeTab === 'api-keys' && <SettingsApiKeys />}
          {activeTab === 'security' && <SettingsSecurity />}
          {activeTab === 'project-types' && (
            <Card className={'p-8'} style={{ borderWidth: '0.5px' }}>
              <p className={'text-[13.5px] text-tertiary'}>
                Project type definitions will be available here.
              </p>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
