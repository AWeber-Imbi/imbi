import { useEffect } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import { Bell, Key, Plug, Shield, User } from 'lucide-react'

import { SettingsAccount } from './settings/SettingsAccount'
import { SettingsApiKeys } from './settings/SettingsApiKeys'
import { SettingsConnections } from './settings/SettingsConnections'
import { SettingsNotifications } from './settings/SettingsNotifications'
import { SettingsSecurity } from './settings/SettingsSecurity'
import { Card } from './ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/tabs'

type SettingsTab =
  | 'account'
  | 'api-keys'
  | 'connections'
  | 'notifications'
  | 'security'

const tabs: { icon: typeof User; id: SettingsTab; label: string }[] = [
  { icon: User, id: 'account', label: 'Account' },
  { icon: Plug, id: 'connections', label: 'Connections' },
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

  const handleTabChange = (tabId: string) => {
    if (isSettingsTab(tabId)) navigate(`/settings/${tabId}`, { replace: true })
  }

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-7">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-primary text-[22px] font-medium">Settings</h1>
        <p className="text-tertiary mt-1 text-[13px]">
          Manage your account preferences and integrations
        </p>
      </div>

      <Tabs
        className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_13fr]"
        onValueChange={handleTabChange}
        orientation="vertical"
        value={activeTab}
      >
        {/* Sidebar navigation */}
        <div>
          <Card className="p-2" style={{ borderWidth: '0.5px' }}>
            <TabsList className="flex h-auto w-full flex-col items-stretch gap-1 border-0 bg-transparent p-0">
              {tabs.map((t) => {
                const Icon = t.icon
                return (
                  <TabsTrigger
                    className="text-secondary hover:bg-secondary aria-selected:bg-warning aria-selected:text-warning justify-start gap-3 rounded-lg border-0 px-4 py-3 text-[13.5px] data-[state=active]:shadow-none"
                    key={t.id}
                    value={t.id}
                  >
                    <Icon className="size-[18px]" />
                    <span>{t.label}</span>
                  </TabsTrigger>
                )
              })}
            </TabsList>
          </Card>
        </div>

        {/* Content area */}
        <div>
          <TabsContent value="account">
            <SettingsAccount />
          </TabsContent>
          <TabsContent value="connections">
            <SettingsConnections />
          </TabsContent>
          <TabsContent value="notifications">
            <SettingsNotifications />
          </TabsContent>
          <TabsContent value="api-keys">
            <SettingsApiKeys />
          </TabsContent>
          <TabsContent value="security">
            <SettingsSecurity />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  )
}
