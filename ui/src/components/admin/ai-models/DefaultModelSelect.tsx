import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { getDefaultAIModel, setDefaultAIModel } from '@/api/endpoints'
import { AIModelSelect } from '@/components/prompts/AIModelSelect'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'

interface DefaultModelSelectProps {
  className?: string
  orgSlug: string
  /** Set for the default of this team; else the organization default. */
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
  const queryKey = queryKeys.defaultAIModel(orgSlug, teamSlug)
  const { data, isLoading } = useQuery({
    queryFn: ({ signal }) => getDefaultAIModel(orgSlug, teamSlug, signal),
    queryKey,
  })
  const mutation = useMutation({
    mutationFn: (slug: null | string) =>
      setDefaultAIModel(orgSlug, slug, teamSlug),
    onError: (err: unknown) => toast.error(extractApiErrorDetail(err)),
    onSuccess: (result) => queryClient.setQueryData(queryKey, result),
  })
  return (
    <AIModelSelect
      ariaLabel={teamSlug ? 'Team default model' : 'Default model'}
      className={className}
      disabled={isLoading || mutation.isPending}
      onChange={(slug) => mutation.mutate(slug)}
      value={data?.slug ?? null}
    />
  )
}
