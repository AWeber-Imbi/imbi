import { useQuery } from '@tanstack/react-query'

import { type EventRecord, getEvent } from '@/api/endpoints'

/**
 * Fetch a single webhook event by id. Used by the deep-link landing
 * in the webhook-history admin view so a shared URL works even when
 * the target event is past the default cursor page.
 */
export function useWebhookEvent(eventId: string | undefined) {
  return useQuery<EventRecord>({
    enabled: Boolean(eventId),
    queryFn: ({ signal }) => {
      if (!eventId) throw new Error('eventId is required')
      return getEvent(eventId, signal)
    },
    queryKey: ['webhookEvent', eventId],
    retry: false,
    staleTime: 60_000,
  })
}
