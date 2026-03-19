import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Power, AlertCircle, CheckCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { getAuthProviders } from '@/api/endpoints'
import type { AuthProvider } from '@/types'

interface OAuthManagementProps {
  isDarkMode: boolean
}

export function OAuthManagement({ isDarkMode }: OAuthManagementProps) {
  const [searchQuery, setSearchQuery] = useState('')

  const { data, isLoading, error } = useQuery({
    queryKey: ['authProviders'],
    queryFn: getAuthProviders,
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
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
        >
          Loading OAuth providers...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-2 rounded-lg p-4 ${
          isDarkMode ? 'bg-red-900/20 text-red-400' : 'bg-red-50 text-red-600'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <span>Failed to load OAuth providers. Please try again later.</span>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div
        className={`flex items-start gap-3 rounded-lg p-4 ${
          isDarkMode
            ? 'border border-blue-800/30 bg-blue-900/20'
            : 'border border-blue-200 bg-blue-50'
        }`}
      >
        <Power
          className={`mt-0.5 h-5 w-5 flex-shrink-0 ${
            isDarkMode ? 'text-blue-400' : 'text-blue-600'
          }`}
        />
        <p
          className={`text-sm ${isDarkMode ? 'text-blue-300' : 'text-blue-700'}`}
        >
          OAuth providers are configured in the backend. Contact an
          administrator to add or modify providers.
        </p>
      </div>

      <div className="relative">
        <Search
          className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
            isDarkMode ? 'text-gray-500' : 'text-gray-400'
          }`}
        />
        <Input
          placeholder="Search providers..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className={`pl-10 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800 text-white placeholder:text-gray-500'
              : 'border-gray-300 bg-white text-gray-900 placeholder:text-gray-400'
          }`}
        />
      </div>

      {filteredProviders.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-12">
          <Power
            className={`mb-3 h-12 w-12 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`}
          />
          <p
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
          >
            {searchQuery
              ? 'No providers match your search.'
              : 'No OAuth providers configured.'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredProviders.map((provider: AuthProvider) => (
            <div
              key={provider.id}
              className={`rounded-lg border p-4 ${
                isDarkMode
                  ? 'border-gray-700 bg-gray-800'
                  : 'border-gray-200 bg-white'
              }`}
            >
              <div className="mb-3 flex items-start justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-xl">
                    {provider.type === 'oauth'
                      ? '\uD83D\uDD12'
                      : '\uD83D\uDD11'}
                  </span>
                  <h3
                    className={`font-medium ${
                      isDarkMode ? 'text-white' : 'text-gray-900'
                    }`}
                  >
                    {provider.name}
                  </h3>
                </div>
                {provider.enabled ? (
                  <CheckCircle className="h-5 w-5 flex-shrink-0 text-green-500" />
                ) : (
                  <AlertCircle
                    className={`h-5 w-5 flex-shrink-0 ${
                      isDarkMode ? 'text-gray-500' : 'text-gray-400'
                    }`}
                  />
                )}
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`inline-flex items-center rounded px-2 py-0.5 text-xs font-medium ${
                    isDarkMode
                      ? 'bg-gray-700 text-gray-300'
                      : 'bg-gray-100 text-gray-600'
                  }`}
                >
                  {provider.type}
                </span>
                <span
                  className={`text-xs ${
                    provider.enabled
                      ? 'text-green-500'
                      : isDarkMode
                        ? 'text-gray-500'
                        : 'text-gray-400'
                  }`}
                >
                  {provider.enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
