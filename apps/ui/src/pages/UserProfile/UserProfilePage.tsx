import { useCallback, useMemo } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'

import { getAdminUser, listUserDocuments } from '@/api/endpoints'
import { CommandBar } from '@/components/CommandBar'
import { Navigation } from '@/components/Navigation'
import { Sk, Swap } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useOrganization } from '@/contexts/OrganizationContext'
import { usePageTitle } from '@/hooks/usePageTitle'

import { fetchContributions, fetchIdentities, fetchStats } from './api'
import { ContributionHeatmap } from './ContributionHeatmap'
import { OrganizationMemberships } from './OrganizationMemberships'
import { ProfileHeader } from './ProfileHeader'
import { RecentActivity } from './RecentActivity'
import { StatisticsCard } from './StatisticsCard'
import { UserDocumentsTab } from './UserDocumentsTab'

// fallow-ignore-next-line complexity
export function UserProfilePage() {
  const navigate = useNavigate()
  const {
    email: rawEmail,
    subAction,
    subId,
    tab,
  } = useParams<{
    email: string
    subAction?: string
    subId?: string
    tab?: string
  }>()
  const email = useMemo(
    () => (rawEmail ? decodeURIComponent(rawEmail) : ''),
    [rawEmail],
  )
  usePageTitle(email ? `Profile · ${email}` : 'User profile')

  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''

  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
  const activeTab = tab === 'documents' ? 'documents' : 'activity'

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

  // Shares the UserDocumentsTab query key so the tab-count chip and the
  // tab content come from the same cache entry.
  const documentsQuery = useQuery({
    enabled: !!email && !!orgSlug,
    queryFn: ({ signal }) => listUserDocuments(orgSlug, email, signal),
    queryKey: ['userDocuments', orgSlug, email],
  })
  const documentCount = documentsQuery.data?.length ?? 0

  const handleTabChange = useCallback(
    (next: string) => {
      const base = `/users/${encodeURIComponent(email)}`
      navigate(next === 'documents' ? `${base}/documents` : base, {
        replace: true,
      })
    },
    [navigate, email],
  )

  return (
    <div className="bg-tertiary text-primary min-h-screen">
      <Navigation currentView="users" />
      <main
        className="px-6 pt-20 pb-12"
        style={{ paddingBottom: 'var(--assistant-height, 64px)' }}
      >
        <div className="mx-auto max-w-5xl space-y-4">
          {userQuery.error && (
            <p className="border-danger bg-danger text-danger rounded-md border p-4 text-sm">
              Could not load profile: {(userQuery.error as Error).message}
            </p>
          )}
          {!userQuery.error && (
            <>
              <Swap
                ready={!!userQuery.data}
                skeleton={<ProfileHeaderSkeleton />}
              >
                {userQuery.data && (
                  <ProfileHeader
                    identities={identitiesQuery.data}
                    user={userQuery.data}
                  />
                )}
              </Swap>
              <Tabs onValueChange={handleTabChange} value={activeTab}>
                <TabsList className="mb-4">
                  <TabsTrigger value="activity">Activity</TabsTrigger>
                  <TabsTrigger value="documents">
                    {documentCount > 0
                      ? `Documents (${documentCount})`
                      : 'Documents'}
                  </TabsTrigger>
                </TabsList>

                <TabsContent className="space-y-4" value="activity">
                  <ContributionHeatmap
                    data={contributionsQuery.data}
                    isLoading={contributionsQuery.isLoading}
                  />
                  <Swap
                    delay={50}
                    ready={!statsQuery.isLoading}
                    skeleton={<StatisticsSkeleton />}
                  >
                    <StatisticsCard data={statsQuery.data} />
                  </Swap>
                  <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
                    <div className="lg:col-span-1">
                      <Swap
                        delay={100}
                        ready={!!userQuery.data}
                        skeleton={<MembershipsSkeleton />}
                      >
                        {userQuery.data && (
                          <OrganizationMemberships user={userQuery.data} />
                        )}
                      </Swap>
                    </div>
                    <div className="lg:col-span-2">
                      <RecentActivity email={email} />
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="documents">
                  {orgSlug && (
                    <UserDocumentsTab
                      email={email}
                      initialAction={
                        activeTab === 'documents' ? subAction : undefined
                      }
                      initialDocumentId={
                        activeTab === 'documents' ? subId : undefined
                      }
                      orgSlug={orgSlug}
                    />
                  )}
                </TabsContent>
              </Tabs>
            </>
          )}
        </div>
      </main>
      <CommandBar />
    </div>
  )
}

function MembershipsSkeleton() {
  return (
    <section
      aria-hidden
      className="border-tertiary bg-primary rounded-md border p-4"
    >
      <Sk className="mb-3" h={14} w={110} />
      <div className="space-y-2">
        {[200, 170, 150].map((w, i) => (
          <div className="flex items-center justify-between" key={i}>
            <Sk h={13} w={w} />
            <Sk h={18} r={2} w={48} />
          </div>
        ))}
      </div>
    </section>
  )
}

function ProfileHeaderSkeleton() {
  return (
    <header
      aria-hidden
      className="border-secondary flex flex-col gap-4 border-b pb-6 md:flex-row md:items-start md:gap-6"
    >
      <Sk h={96} r={6} w={96} />
      <div className="flex-1 space-y-2">
        <Sk h={28} w={220} />
        <Sk h={14} w={140} />
        <Sk h={14} w={200} />
        <div className="flex gap-6 pt-2">
          <Sk h={12} w={120} />
          <Sk h={12} w={120} />
        </div>
      </div>
    </header>
  )
}

function StatisticsSkeleton() {
  return (
    <section aria-hidden className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {[0, 1, 2].map((i) => (
        <div className="border-tertiary rounded-md border p-4" key={i}>
          <Sk h={12} w={110} />
          <Sk className="mt-2" h={28} w={70} />
          <Sk className="mt-1" h={11} w={140} />
        </div>
      ))}
    </section>
  )
}
