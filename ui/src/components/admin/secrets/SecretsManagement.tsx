import { useNavigate, useParams } from 'react-router-dom'

import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOrganization } from '@/contexts/OrganizationContext'

import { AuditTab } from './AuditTab'
import { BindingsTab } from './BindingsTab'
import { GrantsTab } from './GrantsTab'
import { ProvidersTab } from './ProvidersTab'
import { ResolutionsTab } from './ResolutionsTab'

const TABS = [
  ['providers', 'Providers'],
  ['bindings', 'Bindings'],
  ['grants', 'Grants'],
  ['resolutions', 'Resolutions'],
  ['audit', 'Audit'],
] as const

/**
 * The secrets broker of the organization (ADR 0022). The tab is in the
 * URL: /admin/secrets is Providers, /admin/secrets/<tab> the others.
 */
export function SecretsManagement() {
  const navigate = useNavigate()
  const { slug } = useParams<{ slug?: string }>()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const tab = TABS.some(([id]) => id === slug) ? slug : 'providers'
  if (!orgSlug) return null

  return (
    <Tabs
      onValueChange={(value) =>
        navigate(
          value === 'providers' ? '/admin/secrets' : `/admin/secrets/${value}`,
        )
      }
      value={tab}
    >
      <TabsList className="mb-6">
        {TABS.map(([id, label]) => (
          <TabsTrigger key={id} value={id}>
            {label}
          </TabsTrigger>
        ))}
      </TabsList>
      <TabsContent value="providers">
        <ProvidersTab orgSlug={orgSlug} />
      </TabsContent>
      <TabsContent value="bindings">
        <BindingsTab orgSlug={orgSlug} />
      </TabsContent>
      <TabsContent value="grants">
        <GrantsTab orgSlug={orgSlug} />
      </TabsContent>
      <TabsContent value="resolutions">
        <ResolutionsTab orgSlug={orgSlug} />
      </TabsContent>
      <TabsContent value="audit">
        <AuditTab orgSlug={orgSlug} />
      </TabsContent>
    </Tabs>
  )
}
