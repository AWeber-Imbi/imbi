import { useSearchParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { listWebhooks } from '@/api/endpoints'
import { Sk, Swap } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'

import { WebhookHistory } from './WebhookHistory'
import { WebhookManagement } from './WebhookManagement'

type WebhookTab = 'endpoints' | 'history'

// Consolidates the former "Webhooks" and "Webhook History" admin sections into
// a single section with two tabs. Per-endpoint create/edit/detail views (driven
// by a URL slug) are rendered full-bleed without the tab chrome, matching the
// existing management flow.
// fallow-ignore-next-line complexity
export function Webhooks() {
  const { viewMode } = useAdminNav()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const [searchParams, setSearchParams] = useSearchParams()

  const tab: WebhookTab =
    searchParams.get('tab') === 'history' ? 'history' : 'endpoints'
  const eventId = searchParams.get('event') ?? undefined

  const { data: webhooks } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listWebhooks(orgSlug as string, signal),
    queryKey: ['webhooks', orgSlug],
  })

  // A webhook sub-page (create/edit/detail) uses the URL slug; show it on its
  // own without tabs, the same as the standalone management view did.
  if (viewMode !== 'list') {
    return <WebhookManagement />
  }

  const onTabChange = (value: string) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.delete('event')
        if (value === 'history') {
          next.set('tab', 'history')
        } else {
          next.delete('tab')
        }
        return next
      },
      { replace: true },
    )
  }

  return (
    <Tabs onValueChange={onTabChange} value={tab}>
      <TabsList className="mb-6">
        <TabsTrigger value="endpoints">
          Endpoints
          <Swap
            className="ml-2 inline-flex"
            ready={webhooks !== undefined}
            skeleton={<Sk h={18} r={9999} w={22} />}
          >
            <span className="bg-secondary text-secondary rounded-full px-2 py-0.5 font-mono text-xs">
              {webhooks?.length}
            </span>
          </Swap>
        </TabsTrigger>
        <TabsTrigger value="history">Delivery history</TabsTrigger>
      </TabsList>
      <TabsContent value="endpoints">
        <WebhookManagement />
      </TabsContent>
      <TabsContent value="history">
        <WebhookHistory eventId={eventId} />
      </TabsContent>
    </Tabs>
  )
}
