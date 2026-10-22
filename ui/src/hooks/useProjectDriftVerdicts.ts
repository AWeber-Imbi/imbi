import { useQuery } from '@tanstack/react-query'

import { getProjectListItem } from '@/api/endpoints'

// The CI drift verdicts the projects list uses for this project: the
// environment-pair `drift_ranges` and the tag..HEAD `release_summary`.
// Keyed under `releaseDrift` so whatever refreshes the release drift
// (a cut, a sync) refreshes the verdicts too. Until it loads, readers
// see no verdict, and the drift rule then shows drift.
export function useProjectDriftVerdicts(
  orgSlug: string,
  projectId: string,
  enabled = true,
) {
  const { data } = useQuery({
    enabled: enabled && !!orgSlug && !!projectId,
    queryFn: ({ signal }) => getProjectListItem(orgSlug, projectId, signal),
    queryKey: ['releaseDrift', orgSlug, projectId, 'verdicts'],
  })
  return data ?? null
}
