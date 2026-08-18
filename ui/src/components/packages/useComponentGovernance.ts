import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  clearComponentReleaseStatus,
  clearComponentStatus,
  createComponentNote,
  deleteComponentAdvisory,
  setComponentReleaseStatus,
  setComponentStatus,
  upsertComponentAdvisory,
} from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

import { STATUS_LABEL, type StatusValue } from './status'

interface AdvisoryVars {
  componentReleaseId: string
  cveId: string
  title?: string
  url: string
}

interface NoteVars {
  body: string
  componentReleaseId: string
}

interface UseComponentGovernanceResult {
  // `addNote` and `recordAdvisory` resolve only once the write lands,
  // so their dialogs can hold the reader's draft until then; a rejected
  // write must not silently discard what they typed. Both reject on
  // failure -- the error toast is already raised by `onError`, so
  // callers only need the rejection to skip their success step.
  addNote: (vars: NoteVars) => Promise<unknown>
  isPending: boolean
  markComponent: (componentId: string, status: StatusValue) => void
  markVersion: (componentReleaseId: string, status: StatusValue) => void
  recordAdvisory: (vars: AdvisoryVars) => Promise<unknown>
  removeAdvisory: (componentReleaseId: string, cveId: string) => void
}

const message = (err: unknown): string =>
  err instanceof ApiError
    ? (extractApiErrorDetail(err) ?? err.message)
    : (err as Error).message

/**
 * Every write on the package-governance surface, sharing one
 * invalidation set.
 *
 * A mark, an advisory, and a note all change what the two reports show
 * — a version's effective status feeds Problem Packages, and Problem
 * Packages carries the note count — so each write invalidates the usage
 * payload and the report together rather than trying to predict which
 * screen the operator is looking at.
 */
export function useComponentGovernance(
  orgSlug: string,
): UseComponentGovernanceResult {
  const queryClient = useQueryClient()

  const invalidate = (componentReleaseId?: string) => {
    void queryClient.invalidateQueries({ queryKey: ['componentUsage'] })
    // The search dropdown renders each package's status badge, so a
    // mark made here goes stale in every cached search response.
    void queryClient.invalidateQueries({ queryKey: ['componentSearch'] })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.problemPackages(orgSlug),
    })
    if (componentReleaseId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.componentNotes(orgSlug, componentReleaseId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.componentAdvisories(orgSlug, componentReleaseId),
      })
    }
  }

  const componentStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: StatusValue }) =>
      status === 'current'
        ? clearComponentStatus(orgSlug, id)
        : setComponentStatus(orgSlug, id, status),
    onError: (err) => toast.error(message(err)),
    onSuccess: (_data, { status }) => {
      invalidate()
      toast.success(`Package marked ${STATUS_LABEL[status].toLowerCase()}`, {
        description:
          status === 'current'
            ? 'Versions again report their own status.'
            : 'Every version inherits this unless marked more strictly.',
      })
    },
  })

  const versionStatus = useMutation({
    mutationFn: ({ id, status }: { id: string; status: StatusValue }) =>
      status === 'current'
        ? clearComponentReleaseStatus(orgSlug, id)
        : setComponentReleaseStatus(orgSlug, id, status),
    onError: (err) => toast.error(message(err)),
    onSuccess: (_data, { status }) => {
      invalidate()
      toast.success(`Version marked ${STATUS_LABEL[status].toLowerCase()}`)
    },
  })

  const note = useMutation({
    mutationFn: ({ body, componentReleaseId }: NoteVars) =>
      createComponentNote(orgSlug, componentReleaseId, body),
    onError: (err) => toast.error(message(err)),
    onSuccess: (_data, { componentReleaseId }) => {
      invalidate(componentReleaseId)
      toast.success('Note added')
    },
  })

  const advisory = useMutation({
    mutationFn: ({ componentReleaseId, cveId, title, url }: AdvisoryVars) =>
      upsertComponentAdvisory(orgSlug, componentReleaseId, cveId, {
        title: title || null,
        url,
      }),
    onError: (err) => toast.error(message(err)),
    onSuccess: (data, { componentReleaseId }) => {
      invalidate(componentReleaseId)
      toast.success(`Recorded ${data.cve_id}`)
    },
  })

  const advisoryRemoval = useMutation({
    mutationFn: ({
      componentReleaseId,
      cveId,
    }: {
      componentReleaseId: string
      cveId: string
    }) => deleteComponentAdvisory(orgSlug, componentReleaseId, cveId),
    onError: (err) => toast.error(message(err)),
    onSuccess: (_data, { componentReleaseId, cveId }) => {
      invalidate(componentReleaseId)
      toast.success(`Removed ${cveId}`)
    },
  })

  return {
    addNote: (vars) => note.mutateAsync(vars),
    isPending:
      componentStatus.isPending ||
      versionStatus.isPending ||
      note.isPending ||
      advisory.isPending ||
      advisoryRemoval.isPending,
    markComponent: (componentId, status) =>
      componentStatus.mutate({ id: componentId, status }),
    markVersion: (componentReleaseId, status) =>
      versionStatus.mutate({ id: componentReleaseId, status }),
    recordAdvisory: (vars) => advisory.mutateAsync(vars),
    removeAdvisory: (componentReleaseId, cveId) =>
      advisoryRemoval.mutate({ componentReleaseId, cveId }),
  }
}
