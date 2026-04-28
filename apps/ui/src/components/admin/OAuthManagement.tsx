import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle, Power, Search } from 'lucide-react'

import { getAuthProviders } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { LoadingState } from '@/components/ui/loading-state'
import type { AuthProvider } from '@/types'

export function OAuthManagement() {
  const [searchQuery, setSearchQuery] = useState('')

  const { data, error, isLoading } = useQuery({
    queryFn: ({ signal }) => getAuthProviders(signal),
    queryKey: ['authProviders'],
  })

  const providers = data?.providers || []

  const filteredProviders = providers.filter((provider: AuthProvider) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        provider.name.toLowerCase().includes(query) ||
        provider.type.toLowerCase().includes(query)
      )
    }
    return true
  })

  if (isLoading) {
    return <LoadingState label="Loading OAuth providers..." />
  }

  if (error) {
    return <ErrorBanner error={error} title="Failed to load OAuth providers" />
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-3 rounded-lg border border-info bg-info p-4">
        <Power className="mt-0.5 h-5 w-5 flex-shrink-0 text-info" />
        <p className="text-sm text-info">
          OAuth providers are configured in the backend. Contact an
          administrator to add or modify providers.
        </p>
      </div>

      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
        <Input
          className="border-input bg-background pl-10 text-foreground placeholder:text-muted-foreground"
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search providers..."
          value={searchQuery}
        />
      </div>

      {filteredProviders.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12">
          <Power className="mb-3 h-12 w-12 text-secondary" />
          <p className="text-sm text-tertiary">
            {searchQuery
              ? 'No providers match your search.'
              : 'No OAuth providers configured.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredProviders.map((provider: AuthProvider) => (
            <Card key={provider.id}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <div className="flex items-center gap-2">
                  <span className="text-xl">
                    {provider.type === 'oauth'
                      ? '\uD83D\uDD12'
                      : '\uD83D\uDD11'}
                  </span>
                  <CardTitle>{provider.name}</CardTitle>
                </div>
                {provider.enabled ? (
                  <CheckCircle className="h-5 w-5 flex-shrink-0 text-green-500" />
                ) : (
                  <AlertCircle className="h-5 w-5 flex-shrink-0 text-tertiary" />
                )}
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Badge variant="neutral">{provider.type}</Badge>
                  <span
                    className={`text-xs ${
                      provider.enabled ? 'text-success' : 'text-tertiary'
                    }`}
                  >
                    {provider.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
