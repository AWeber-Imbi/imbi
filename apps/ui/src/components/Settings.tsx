import { useEffect } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import { ArrowLeft, Bell, Key, Link2, Plug, Shield, User } from 'lucide-react'

import { SettingsAccount } from './settings/SettingsAccount'
import { SettingsApiKeys } from './settings/SettingsApiKeys'
import { SettingsConnections } from './settings/SettingsConnections'
import { SettingsIntegrations } from './settings/SettingsIntegrations'
import { SettingsNotifications } from './settings/SettingsNotifications'
import { SettingsSecurity } from './settings/SettingsSecurity'
import { Button } from './ui/button'
import { Card } from './ui/card'

type SettingsTab =
  | 'account'
  | 'api-keys'
  | 'connections'
  | 'integrations'
  | 'notifications'
  | 'security'

const tabs: { icon: typeof User; id: SettingsTab; label: string }[] = [
  { icon: User, id: 'account', label: 'Account' },
  { icon: Plug, id: 'connections', label: 'Connections' },
  { icon: Link2, id: 'integrations', label: 'Integrations' },
  { icon: Bell, id: 'notifications', label: 'Notifications' },
  { icon: Key, id: 'api-keys', label: 'API Keys' },
  { icon: Shield, id: 'security', label: 'Security' },
]

const isSettingsTab = (value: string): value is SettingsTab =>
  tabs.some((t) => t.id === value)

export function Settings() {
  const navigate = useNavigate()
  const { tab } = useParams<{ tab?: string }>()
  const activeTab: SettingsTab = tab && isSettingsTab(tab) ? tab : 'account'

  useEffect(() => {
    if (tab && !isSettingsTab(tab)) {
      navigate('/settings/account', { replace: true })
    }
  }, [tab, navigate])

  const handleTabChange = (tabId: SettingsTab) => {
    navigate(`/settings/${tabId}`, { replace: true })
  }

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-7">
      {/* Back button */}
      <Button
        className="mb-6 gap-2 text-secondary hover:bg-secondary"
        onClick={() => navigate(-1)}
        variant="ghost"
      >
        <ArrowLeft className="h-4 w-4" />
        Back
      </Button>

      {/* Header */}
      <div className="mb-8">
        <h1 className="text-[22px] font-medium text-primary">Settings</h1>
        <p className="mt-1 text-[13px] text-tertiary">
          Manage your account preferences and integrations
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* Sidebar navigation */}
        <div className="lg:col-span-1">
          <Card className="p-2" style={{ borderWidth: '0.5px' }}>
            <nav className="space-y-1">
              {tabs.map((t) => {
                const Icon = t.icon
                return (
                  <button
                    className={`flex w-full items-center gap-3 rounded-lg px-4 py-3 text-[13.5px] transition-colors ${
                      activeTab === t.id
                        ? 'bg-warning text-warning'
                        : 'text-secondary hover:bg-secondary'
                    }`}
                    key={t.id}
                    onClick={() => handleTabChange(t.id)}
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
          {activeTab === 'connections' && <SettingsConnections />}
          {activeTab === 'integrations' && <SettingsIntegrations />}
          {activeTab === 'notifications' && <SettingsNotifications />}
          {activeTab === 'api-keys' && <SettingsApiKeys />}
          {activeTab === 'security' && <SettingsSecurity />}
        </div>
      </div>
    </div>
  )
}
