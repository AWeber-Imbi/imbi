import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { getDefaultAIModel, setDefaultAIModel } from '@/api/endpoints'
import { AIModelSelect } from '@/components/prompts/AIModelSelect'
import { Button } from '@/components/ui/button'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

interface DefaultModelSelectProps {
  className?: string
  orgSlug: string
  /** Set for the default of this team; else the organization default. */
  teamSlug?: string
}

interface SaveVariables {
  orgSlug: string
  slug: null | string
  teamSlug?: string
}

/**
 * The model a call uses when its prompt or step names none. The team
 * default comes before the organization default (ADR 0018).
 */
export function DefaultModelSelect({
  className,
  orgSlug,
  teamSlug,
}: DefaultModelSelectProps) {
  const queryClient = useQueryClient()
  const { data, isError, isLoading, refetch } = useQuery({
    queryFn: ({ signal }) => getDefaultAIModel(orgSlug, teamSlug, signal),
    queryKey: queryKeys.defaultAIModel(orgSlug, teamSlug),
  })
  const mutation = useMutation({
    mutationFn: (vars: SaveVariables) =>
      setDefaultAIModel(vars.orgSlug, vars.slug, vars.teamSlug),
    onError: (err: unknown) => toast.error(extractApiErrorDetail(err)),
    // The scope of the request, which can differ from the current props.
    // Cancel a read in flight, so that its older result does not
    // overwrite the saved value.
    onSuccess: async (result, vars) => {
      const queryKey = queryKeys.defaultAIModel(vars.orgSlug, vars.teamSlug)
      await queryClient.cancelQueries({ queryKey })
      queryClient.setQueryData(queryKey, result)
    },
  })
  if (isError && data === undefined) {
    return (
      <p className="text-danger flex items-center gap-2 text-xs">
        Could not load the default model.
        <Button onClick={() => void refetch()} size="sm" variant="ghost">
          Retry
        </Button>
      </p>
    )
  }
  return (
    <AIModelSelect
      ariaLabel={teamSlug ? 'Team default model' : 'Default model'}
      className={className}
      disabled={isLoading || mutation.isPending}
      onChange={(slug) => mutation.mutate({ orgSlug, slug, teamSlug })}
      value={data?.slug ?? null}
    />
  )
}
