// Releases-tab API calls (build-and-release-only projects). Kept separate
// from the large endpoints.ts so this focused surface stays readable.
import type {
  CutReleaseRequest,
  CutReleaseResponse,
  ReleaseBlocker,
  ReleaseBlockerCreateRequest,
  ReleaseBlockResponse,
  ReleaseDrift,
  ReleaseHistoryEntry,
} from '@/types'

import { apiClient } from './client'

const base = (orgSlug: string, projectId: string): string =>
  `/organizations/${encodeURIComponent(orgSlug)}/projects/${encodeURIComponent(projectId)}/deployments`

export const getReleaseDrift = (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<ReleaseDrift> =>
  apiClient.get<ReleaseDrift>(
    `${base(orgSlug, projectId)}/release-drift`,
    undefined,
    signal,
  )

export const getReleaseHistory = async (
  orgSlug: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<ReleaseHistoryEntry[]> => {
  const response = await apiClient.get<ReleaseHistoryEntry[]>(
    `${base(orgSlug, projectId)}/release-history`,
    undefined,
    signal,
  )
  if (!Array.isArray(response)) {
    throw new Error('Unexpected release-history response: expected an array')
  }
  return response
}

export const cutRelease = (
  orgSlug: string,
  projectId: string,
  body: CutReleaseRequest,
): Promise<CutReleaseResponse> =>
  apiClient.post<CutReleaseResponse>(
    `${base(orgSlug, projectId)}/releases/cut`,
    body,
  )

const blockPath = (orgSlug: string, projectId: string, tag: string): string =>
  `${base(orgSlug, projectId)}/releases/${encodeURIComponent(tag)}/block`

export const unblockRelease = (
  orgSlug: string,
  projectId: string,
  tag: string,
): Promise<ReleaseBlockResponse> =>
  apiClient.delete<ReleaseBlockResponse>(blockPath(orgSlug, projectId, tag))

const blockersPath = (
  orgSlug: string,
  projectId: string,
  tag: string,
): string =>
  `${base(orgSlug, projectId)}/releases/${encodeURIComponent(tag)}/blockers`

export const addReleaseBlocker = (
  orgSlug: string,
  projectId: string,
  tag: string,
  body: ReleaseBlockerCreateRequest,
): Promise<ReleaseBlocker> =>
  apiClient.post<ReleaseBlocker>(blockersPath(orgSlug, projectId, tag), body)

export const resolveReleaseBlocker = (
  orgSlug: string,
  projectId: string,
  tag: string,
  blockerId: string,
  resolutionNote?: string,
): Promise<ReleaseBlocker> =>
  apiClient.post<ReleaseBlocker>(
    `${blockersPath(orgSlug, projectId, tag)}/${encodeURIComponent(blockerId)}/resolve`,
    { resolution_note: resolutionNote ?? null },
  )
