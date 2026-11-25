import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { createOrFindTag, listTags } from '@/api/endpoints'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type { Tag, TagRef } from '@/types'

/** The fields of an org tag that a chip shows, copied from any tag. */
export function tagRef(tag: TagRef): TagRef {
  return { color: tag.color, name: tag.name, slug: tag.slug }
}

/**
 * The org tags, and a mutation that creates a tag (or finds the tag with
 * that slug). `onCreated` gets the tag after the list is invalidated.
 */
export function useOrgTags(orgSlug: string, onCreated: (tag: Tag) => void) {
  const queryClient = useQueryClient()
  const tagsKey = queryKeys.tags(orgSlug)
  const { data: tags = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTags(orgSlug, signal),
    queryKey: tagsKey,
  })
  const create = useMutation({
    mutationFn: (data: Parameters<typeof createOrFindTag>[1]) =>
      createOrFindTag(orgSlug, data),
    onError: (error) =>
      toast.error(`Failed to create the tag: ${extractApiErrorDetail(error)}`),
    onSuccess: (tag) => {
      void queryClient.invalidateQueries({ queryKey: tagsKey })
      onCreated(tag)
    },
  })
  return { create, tags }
}
