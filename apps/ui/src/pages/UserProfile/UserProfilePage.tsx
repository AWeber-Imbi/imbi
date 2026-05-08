import { useMemo } from 'react'

import { useParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getAdminUser } from '@/api/endpoints'
import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { usePageTitle } from '@/hooks/usePageTitle'

import { fetchContributions, fetchIdentities, fetchStats } from './api'
import { ContributionHeatmap } from './ContributionHeatmap'
import { OrganizationMemberships } from './OrganizationMemberships'
import { ProfileHeader } from './ProfileHeader'
import { RecentActivity } from './RecentActivity'
import { StatisticsCard } from './StatisticsCard'

export function UserProfilePage() {
  const { email: rawEmail } = useParams<{ email: string }>()
  const email = useMemo(
    () => (rawEmail ? decodeURIComponent(rawEmail) : ''),
    [rawEmail],
  )
  usePageTitle(email ? `Profile · ${email}` : 'User profile')

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone

  const userQuery = useQuery({
    enabled: !!email,
    queryFn: ({ signal }) => getAdminUser(email, signal),
    queryKey: ['user', email],
  })

  const contributionsQuery = useQuery({
    enabled: !!email,
    queryFn: ({ signal }) => fetchContributions(email, { tz }, signal),
    queryKey: ['user-contributions', email, tz],
  })

  const statsQuery = useQuery({
    enabled: !!email,
    queryFn: ({ signal }) => fetchStats(email, { tz }, signal),
    queryKey: ['user-stats', email, tz],
  })

  const identitiesQuery = useQuery({
    enabled: !!email,
    queryFn: ({ signal }) => fetchIdentities(email, signal),
    queryKey: ['user-identities', email],
  })

  return (
    <div className="min-h-screen bg-tertiary text-primary">
      <Navigation currentView="users" />
      <main
        className="px-6 pb-12 pt-20"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <div className="mx-auto max-w-5xl space-y-4">
          {userQuery.error && (
            <p className="rounded-md border border-danger bg-danger p-4 text-sm text-danger">
              Could not load profile: {(userQuery.error as Error).message}
            </p>
          )}
          {userQuery.data && (
            <>
              <ProfileHeader
                identities={identitiesQuery.data}
                user={userQuery.data}
              />
              <ContributionHeatmap
                data={contributionsQuery.data}
                isLoading={contributionsQuery.isLoading}
              />
              <StatisticsCard data={statsQuery.data} />
              <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                <div className="lg:col-span-1">
                  <OrganizationMemberships user={userQuery.data} />
                </div>
                <div className="lg:col-span-2">
                  <RecentActivity email={email} />
                </div>
              </div>
            </>
          )}
        </div>
      </main>
      <CommandBar />
    </div>
  )
}
