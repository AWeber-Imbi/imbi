import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'

import { extractApiErrorDetail } from '@/lib/apiError'

interface AdminCrudConfig<TItem, TCreateInput, TUpdateInput, TDeleteInput> {
  /**
   * How to surface create/update errors. Forms that render error inline
   * should pass `'silent'`. Defaults to `'silent'` (matches existing
   * behavior — pages rely on forms to show errors).
   */
  createErrorMode?: ErrorMode
  /** Create mutation handler. */
  createFn: (input: TCreateInput) => Promise<unknown>
  /** Toasted-on-delete-failure label, e.g. "team" → "Failed to delete team". */
  deleteErrorLabel: string
  /** Delete mutation handler. */
  deleteFn: (input: TDeleteInput) => Promise<unknown>
  /** Additional queryKeys to invalidate after any mutation. */
  extraInvalidateKeys?: QueryKey[]
  /** Fetch the list. Return [] to disable via enabled=false. */
  listFn: ((signal?: AbortSignal) => Promise<TItem[]>) | null
  /** Called after a successful create or update (typically goToList). */
  onMutationSuccess?: () => void
  /** React Query key for the list query. */
  queryKey: QueryKey
  updateErrorMode?: ErrorMode
  /** Update mutation handler. */
  updateFn: (input: TUpdateInput) => Promise<unknown>
}

type ErrorMode = 'silent' | 'toast'

export function useAdminCrud<
  TItem,
  TCreateInput = unknown,
  TUpdateInput = unknown,
  TDeleteInput = unknown,
>(config: AdminCrudConfig<TItem, TCreateInput, TUpdateInput, TDeleteInput>) {
  const queryClient = useQueryClient()
  const {
    createErrorMode = 'silent',
    createFn,
    deleteErrorLabel,
    deleteFn,
    extraInvalidateKeys,
    listFn,
    onMutationSuccess,
    queryKey,
    updateErrorMode = 'silent',
    updateFn,
  } = config

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey })
    extraInvalidateKeys?.forEach((k) =>
      queryClient.invalidateQueries({ queryKey: k }),
    )
  }

  const listQuery = useQuery<TItem[]>({
    enabled: !!listFn,
    queryFn: ({ signal }) =>
      listFn ? listFn(signal) : Promise.resolve([] as TItem[]),
    queryKey,
  })

  const createMutation = useMutation<unknown, Error, TCreateInput>({
    mutationFn: createFn,
    onError: (error) => {
      if (createErrorMode === 'toast') {
        toast.error(
          `Failed to create ${deleteErrorLabel}: ${extractApiErrorDetail(error)}`,
        )
      }
      // 'silent' mode: consumer renders error inline via mutation state.
    },
    onSuccess: () => {
      invalidate()
      onMutationSuccess?.()
    },
  })

  const updateMutation = useMutation<unknown, Error, TUpdateInput>({
    mutationFn: updateFn,
    onError: (error) => {
      if (updateErrorMode === 'toast') {
        toast.error(
          `Failed to update ${deleteErrorLabel}: ${extractApiErrorDetail(error)}`,
        )
      }
      // 'silent' mode: consumer renders error inline via mutation state.
    },
    onSuccess: () => {
      invalidate()
      onMutationSuccess?.()
    },
  })

  const deleteMutation = useMutation<unknown, Error, TDeleteInput>({
    mutationFn: deleteFn,
    onError: (error) => {
      toast.error(
        `Failed to delete ${deleteErrorLabel}: ${extractApiErrorDetail(error)}`,
      )
    },
    onSuccess: () => {
      invalidate()
    },
  })

  return {
    createMutation,
    deleteMutation,
    error: listQuery.error,
    isLoading: listQuery.isLoading,
    items: listQuery.data ?? [],
    updateMutation,
  }
}
