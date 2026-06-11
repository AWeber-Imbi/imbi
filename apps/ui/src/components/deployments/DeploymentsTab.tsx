import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listCurrentReleases, listRecentCommits } from '@/api/endpoints'
import { getReleaseHistory } from '@/api/releases'
import type { DeploymentRunStarted } from '@/components/deploy/DeploymentModal'
import { LoadingState } from '@/components/ui/loading-state'
import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import type { Environment } from '@/types'

import { EnvironmentDetail } from './EnvironmentDetail'
import { EnvironmentNav } from './EnvironmentNav'
import { buildPipeline, defaultStageSlug } from './pipeline'
import { useDeploymentActions } from './useDeploymentActions'
import { useDeploymentSync } from './useDeploymentSync'

interface DeploymentsTabProps {
  canTrigger: boolean
  connectLabel: string
  /** Pipeline environments, already sorted ascending by sort_order. */
  environments: Environment[]
  onRunStarted?: (run: DeploymentRunStarted) => void
  orgSlug: string
  projectId: string
  readiness: 'connected' | 'disconnected' | 'error' | 'loading'
  /** Third-party service powering the deployment plugin. */
  serviceIcon: null | string
  serviceLabel: null | string
}

// Synced default-branch commits to consider; covers the realistic gap
// between the oldest deployed environment and the branch tip.
const COMMIT_WINDOW = 200

/**
 * Project-detail Deployments tab: an environment sidebar (descending
 * sort order) and a per-environment detail pane for deploying,
 * promoting, and rolling back.
 *
 * Reads exclusively from imbi's synced data (graph releases + the
 * ClickHouse commit/tag history) — never the live source host. The
 * sidebar's sync action refreshes commits, tags, and releases.
 */
// fallow-ignore-next-line complexity
export function DeploymentsTab({
  canTrigger,
  connectLabel,
  environments,
  onRunStarted,
  orgSlug,
  projectId,
  readiness,
  serviceIcon,
  serviceLabel,
}: DeploymentsTabProps) {
  const { isDarkMode } = useTheme()
  const enabled = !!orgSlug && !!projectId

  const {
    data: currentReleases = [],
    error: currentError,
    isLoading: currentLoading,
  } = useQuery({
    enabled,
    queryFn: ({ signal }) => listCurrentReleases(orgSlug, projectId, signal),
    queryKey: ['currentReleases', orgSlug, projectId],
  })
  const {
    data: history = [],
    error: historyError,
    isLoading: historyLoading,
  } = useQuery({
    enabled,
    queryFn: ({ signal }) => getReleaseHistory(orgSlug, projectId, signal),
    queryKey: ['releaseHistory', orgSlug, projectId],
  })
  const {
    data: recentCommits = [],
    error: commitsError,
    isLoading: commitsLoading,
  } = useQuery({
    enabled,
    queryFn: ({ signal }) =>
      listRecentCommits(orgSlug, projectId, { limit: COMMIT_WINDOW }, signal),
    queryKey: ['recentCommits', orgSlug, projectId],
  })

  const stages = useMemo(
    () => buildPipeline(environments, currentReleases, history, recentCommits),
    [environments, currentReleases, history, recentCommits],
  )

  const [selectedSlug, setSelectedSlug] = useState<null | string>(null)
  const effectiveSlug =
    selectedSlug && stages.some((s) => s.env.slug === selectedSlug)
      ? selectedSlug
      : defaultStageSlug(stages)
  const selectedStage = stages.find((s) => s.env.slug === effectiveSlug) ?? null

  const actions = useDeploymentActions({ onRunStarted, orgSlug, projectId })
  const { isSyncing, sync } = useDeploymentSync(orgSlug, projectId)

  if (currentLoading || historyLoading || commitsLoading) {
    return <LoadingState label="Loading deployments…" />
  }
  if (currentError || historyError || commitsError) {
    return (
      <div className="border-tertiary text-tertiary rounded-lg border p-6 text-center text-sm">
        Could not load deployment data for this project.
      </div>
    )
  }
  if (stages.length === 0) {
    return (
      <div className="border-tertiary text-tertiary rounded-lg border p-6 text-center text-sm">
        No environments are configured for this project.
      </div>
    )
  }

  return (
    <div className="grid items-start gap-5 md:grid-cols-[240px_minmax(0,1fr)]">
      <EnvironmentNav
        connectLabel={connectLabel}
        isDarkMode={isDarkMode}
        isSyncing={isSyncing}
        onSelect={setSelectedSlug}
        onSync={sync}
        readiness={readiness}
        selectedSlug={effectiveSlug}
        serviceIcon={serviceIcon}
        serviceLabel={serviceLabel}
        stages={stages}
      />
      {selectedStage ? (
        <EnvironmentDetail
          accent={
            selectedStage.env.label_color
              ? deriveChipColors(selectedStage.env.label_color, isDarkMode)
              : null
          }
          actions={actions}
          canTrigger={canTrigger}
          orgSlug={orgSlug}
          projectId={projectId}
          recentCommits={recentCommits}
          stage={selectedStage}
        />
      ) : null}
    </div>
  )
}
