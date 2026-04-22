import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { QueryKey } from '@tanstack/react-query'
import { toast } from 'sonner'
import { extractApiErrorDetail } from '@/lib/apiError'

type ErrorMode = 'toast' | 'silent'

interface AdminCrudConfig<TItem, TCreateInput, TUpdateInput, TDeleteInput> {
  /** React Query key for the list query. */
  queryKey: QueryKey
  /** Fetch the list. Return [] to disable via enabled=false. */
  listFn: (() => Promise<TItem[]>) | null
  /** Create mutation handler. */
  createFn: (input: TCreateInput) => Promise<unknown>
  /** Update mutation handler. */
  updateFn: (input: TUpdateInput) => Promise<unknown>
  /** Delete mutation handler. */
  deleteFn: (input: TDeleteInput) => Promise<unknown>
  /** Called after a successful create or update (typically goToList). */
  onMutationSuccess?: () => void
  /** Additional queryKeys to invalidate after any mutation. */
  extraInvalidateKeys?: QueryKey[]
  /**
   * How to surface create/update errors. Forms that render error inline
   * should pass `'silent'`. Defaults to `'silent'` (matches existing
   * behavior — pages rely on forms to show errors).
   */
  createErrorMode?: ErrorMode
  updateErrorMode?: ErrorMode
  /** Toasted-on-delete-failure label, e.g. "team" → "Failed to delete team". */
  deleteErrorLabel: string
}

export function useAdminCrud<
  TItem,
  TCreateInput = unknown,
  TUpdateInput = unknown,
  TDeleteInput = unknown,
>(config: AdminCrudConfig<TItem, TCreateInput, TUpdateInput, TDeleteInput>) {
  const queryClient = useQueryClient()
  const {
    queryKey,
    listFn,
    createFn,
    updateFn,
    deleteFn,
    onMutationSuccess,
    extraInvalidateKeys,
    createErrorMode = 'silent',
    updateErrorMode = 'silent',
    deleteErrorLabel,
  } = config

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey })
    extraInvalidateKeys?.forEach((k) =>
      queryClient.invalidateQueries({ queryKey: k }),
    )
  }

  const listQuery = useQuery<TItem[]>({
    queryKey,
    queryFn: listFn ?? (() => Promise.resolve([] as TItem[])),
    enabled: !!listFn,
  })

  const createMutation = useMutation<unknown, Error, TCreateInput>({
    mutationFn: createFn,
    onSuccess: () => {
      invalidate()
      onMutationSuccess?.()
    },
    onError: (error) => {
      if (createErrorMode === 'toast') {
        toast.error(
          `Failed to create ${deleteErrorLabel}: ${extractApiErrorDetail(error)}`,
        )
      }
      // 'silent' mode: consumer renders error inline via mutation state.
    },
  })

  const updateMutation = useMutation<unknown, Error, TUpdateInput>({
    mutationFn: updateFn,
    onSuccess: () => {
      invalidate()
      onMutationSuccess?.()
    },
    onError: (error) => {
      if (updateErrorMode === 'toast') {
        toast.error(
          `Failed to update ${deleteErrorLabel}: ${extractApiErrorDetail(error)}`,
        )
      }
      // 'silent' mode: consumer renders error inline via mutation state.
    },
  })

  const deleteMutation = useMutation<unknown, Error, TDeleteInput>({
    mutationFn: deleteFn,
    onSuccess: () => {
      invalidate()
    },
    onError: (error) => {
      toast.error(
        `Failed to delete ${deleteErrorLabel}: ${extractApiErrorDetail(error)}`,
      )
    },
  })

  return {
    items: listQuery.data ?? [],
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    updateMutation,
    deleteMutation,
  }
}
