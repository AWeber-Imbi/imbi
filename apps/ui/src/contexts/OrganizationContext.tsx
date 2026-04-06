/* eslint-disable react-refresh/only-export-components */
import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'
import { listOrganizations } from '@/api/endpoints'
import { useAuthStore } from '@/stores/authStore'
import type { Organization } from '@/types'

const ORG_STORAGE_KEY = 'imbi-selected-org'

interface OrganizationContextValue {
  organizations: Organization[]
  selectedOrganization: Organization | null
  setSelectedOrganization: (org: Organization) => void
  isLoading: boolean
}

const OrganizationContext = createContext<OrganizationContextValue | null>(null)

export function OrganizationProvider({ children }: { children: ReactNode }) {
  const [selectedSlug, setSelectedSlug] = useState<string | null>(() =>
    localStorage.getItem(ORG_STORAGE_KEY),
  )

  const { accessToken, isTokenExpired } = useAuthStore()

  const { data: organizations = [], isLoading } = useQuery({
    queryKey: ['organizations'],
    queryFn: listOrganizations,
    enabled: !!accessToken && !isTokenExpired(),
    retry: 1,
  })

  // Auto-select when orgs load and nothing valid is selected
  useEffect(() => {
    if (organizations.length === 0) return
    const current = organizations.find((o) => o.slug === selectedSlug)
    if (!current) {
      const firstOrg = organizations[0]
      localStorage.setItem(ORG_STORAGE_KEY, firstOrg.slug)
      setSelectedSlug(firstOrg.slug)
    }
  }, [organizations, selectedSlug])

  const selectedOrganization =
    organizations.find((o) => o.slug === selectedSlug) || null

  const setSelectedOrganization = useCallback((org: Organization) => {
    localStorage.setItem(ORG_STORAGE_KEY, org.slug)
    setSelectedSlug(org.slug)
  }, [])

  return (
    <OrganizationContext.Provider
      value={{
        organizations,
        selectedOrganization,
        setSelectedOrganization,
        isLoading,
      }}
    >
      {children}
    </OrganizationContext.Provider>
  )
}

export function useOrganization() {
  const context = useContext(OrganizationContext)
  if (!context) {
    throw new Error(
      'useOrganization must be used within an OrganizationProvider',
    )
  }
  return context
}
