import { useEffect, useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'

import { listDeploymentRefs, listRefCommits } from '@/api/endpoints'
import type { DeploymentCommit, DeploymentRef } from '@/types'

interface UseBranchPickerOptions {
  envSlug: string
  isFirstEnv: boolean
  open: boolean
  orgSlug: string
  projectId: string
}

interface UseBranchPickerResult {
  activeBranch: null | string
  activeBranchCommits: DeploymentCommit[]
  activeBranchError: boolean
  activeBranchLoading: boolean
  activeBranchRefetch: () => void
  branchesError: boolean
  branchesLoading: boolean
  branchesRefetch: () => void
  branchQuery: string
  branchRefs: DeploymentRef[]
  filteredBranches: DeploymentRef[]
  pickerMode: 'branches' | 'default'
  setActiveBranch: (name: null | string) => void
  setBranchQuery: (q: string) => void
  setPickerMode: (mode: 'branches' | 'default') => void
  showBranchPane: boolean
}

export function useBranchPicker({
  envSlug,
  isFirstEnv,
  open,
  orgSlug,
  projectId,
}: UseBranchPickerOptions): UseBranchPickerResult {
  const [pickerMode, setPickerMode] = useState<'branches' | 'default'>(
    'default',
  )
  const [branchQuery, setBranchQuery] = useState('')
  const [activeBranch, setActiveBranch] = useState<null | string>(null)
  useEffect(() => {
    setPickerMode('default')
    setActiveBranch(null)
    setBranchQuery('')
  }, [envSlug])

  const showBranchPane = isFirstEnv && pickerMode === 'branches'

  const {
    data: branchRefs = [],
    isError: branchesError,
    isLoading: branchesLoading,
    refetch: branchesRefetch,
  } = useQuery<DeploymentRef[]>({
    enabled: open && showBranchPane,
    queryFn: ({ signal }) =>
      listDeploymentRefs(orgSlug, projectId, { kind: 'branch' }, signal),
    queryKey: ['deploymentRefs', orgSlug, projectId, 'branch'],
  })

  const filteredBranches = useMemo(() => {
    const q = branchQuery.trim().toLowerCase()
    if (!q) return branchRefs
    return branchRefs.filter((b) => b.name.toLowerCase().includes(q))
  }, [branchRefs, branchQuery])

  const {
    data: activeBranchCommits = [],
    isError: activeBranchError,
    isLoading: activeBranchLoading,
    refetch: activeBranchRefetch,
  } = useQuery<DeploymentCommit[]>({
    enabled: open && showBranchPane && !!activeBranch,
    queryFn: ({ signal }) =>
      listRefCommits(
        orgSlug,
        projectId,
        activeBranch ?? '',
        { limit: 25 },
        signal,
      ),
    queryKey: ['refCommits', orgSlug, projectId, activeBranch],
  })

  return {
    activeBranch,
    activeBranchCommits,
    activeBranchError,
    activeBranchLoading,
    activeBranchRefetch,
    branchesError,
    branchesLoading,
    branchesRefetch,
    branchQuery,
    branchRefs,
    filteredBranches,
    pickerMode,
    setActiveBranch,
    setBranchQuery,
    setPickerMode,
    showBranchPane,
  }
}
