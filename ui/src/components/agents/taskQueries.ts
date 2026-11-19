import { useEffect, useRef } from 'react'

import {
  keepPreviousData,
  type QueryKey,
  useMutation,
  useQueries,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import {
  countTickets,
  countWaitingTickets,
  getTicket,
  getTicketRelations,
  listTicketEvents,
  listTicketProjects,
  listTickets,
  replyTicket,
  type TicketListParams,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { Ticket, TicketEvent } from '@/types'

export type TaskReply = ReturnType<typeof useTaskReply>

/** How often a live task reads new events (O4). */
export const EVENT_POLL_MS = 3000

/** How often the inbox and the "waiting on you" count refresh. */
const LIST_POLL_MS = 15_000

const EVENT_PAGE = 500

/** The tasks in each page of an inbox group. */
export const TASK_PAGE = 50

/** The event types that change the relations of a task. */
const RELATION_EVENTS = new Set([
  'dependency.added',
  'dependency.removed',
  'project.associated',
  'project.dissociated',
])

/** The `detail` text of an API error, or its message. */
export function errorMessage(error: Error): string {
  if (error instanceof ApiError) {
    const detail = (error.data as undefined | { detail?: unknown })?.detail
    if (typeof detail === 'string') return detail
    if (detail && typeof detail === 'object' && 'message' in detail)
      return String(detail.message)
  }
  return error.message
}

/**
 * The reply mutation of a task, owned above the views so a pending reply
 * stays pending when the composer remounts.
 */
export function useTaskReply(orgSlug: string, shortId: string) {
  return useTicketMutation(
    orgSlug,
    shortId,
    ({ hold, text }: { hold: boolean; text: string }) =>
      replyTicket(orgSlug, shortId, text.trim(), hold),
  )
}

export function useTicket(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => getTicket(orgSlug, shortId, signal),
    queryKey: queryKeys.ticket(orgSlug, shortId),
  })
}

/**
 * The number of tasks in each inbox group. A change of filters keeps
 * the old counts until the new ones come, so the list does not jump.
 */
export function useTicketCounts(orgSlug: string, params: TicketListParams) {
  return useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => countTickets(orgSlug, params, signal),
    queryKey: queryKeys.tickets(orgSlug, { ...params, counts: true }),
    refetchInterval: LIST_POLL_MS,
  })
}

/**
 * The events of a task. Each refetch reads only the events after the
 * newest one in the cache and appends them, so polling is cheap and the
 * page never reloads. Polls while `live`.
 */
export function useTicketEvents(
  orgSlug: string,
  shortId: string,
  live: boolean,
) {
  const queryClient = useQueryClient()
  const queryKey = queryKeys.ticketEvents(orgSlug, shortId)
  const query = useQuery({
    queryFn: async ({ signal }) => {
      const have = queryClient.getQueryData<TicketEvent[]>(queryKey) ?? []
      const events = [...have]
      for (;;) {
        const page = await listTicketEvents(
          orgSlug,
          shortId,
          events[events.length - 1]?.seq ?? 0,
          EVENT_PAGE,
          signal,
        )
        events.push(...page)
        if (page.length < EVENT_PAGE) break
      }
      return events.length === have.length ? have : events
    },
    queryKey,
    refetchInterval: live ? EVENT_POLL_MS : false,
  })
  // A new event can change the task (status, phase, totals), so the
  // task, the inbox, and the waiting count read it again; a relation
  // event, also the relations. Before the first event read, the task
  // reference is the `last_seq` of the cached task, because the task
  // can change between the two reads. The relations do not use that
  // reference: they are a different read, so the first event read
  // refreshes them if it contains a relation event.
  const data = query.data
  const seenSeq = useRef(0)
  useEffect(() => {
    const lastSeq = data?.[data.length - 1]?.seq ?? 0
    const taskKey = queryKeys.ticket(orgSlug, shortId)
    const previousSeq = seenSeq.current
    const base =
      previousSeq ||
      (queryClient.getQueryData<Ticket>(taskKey)?.last_seq ?? lastSeq)
    const keys: QueryKey[] = []
    if (lastSeq > base)
      keys.push(
        taskKey,
        queryKeys.tickets(orgSlug),
        queryKeys.ticketsWaiting(orgSlug),
      )
    if (data?.some((e) => e.seq > previousSeq && RELATION_EVENTS.has(e.type)))
      keys.push(
        queryKeys.ticketRelations(orgSlug, shortId),
        queryKeys.ticketProjects(orgSlug, shortId),
      )
    for (const key of keys)
      void queryClient.invalidateQueries({ queryKey: key })
    seenSeq.current = lastSeq
  }, [data, orgSlug, shortId, queryClient])
  return query
}

/**
 * The pages of the inbox groups that `pages` names, as
 * `<group>:<page>`, each `TASK_PAGE` tasks in the order of the inbox.
 */
export function useTicketGroupPages(
  orgSlug: string,
  params: TicketListParams,
  pages: string[],
) {
  return useQueries({
    queries: pages.map((name) => {
      const [group, page] = name.split(':') as [
        NonNullable<TicketListParams['group']>,
        string,
      ]
      const offset = Number(page) * TASK_PAGE
      return {
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          listTickets(
            orgSlug,
            { ...params, group, limit: TASK_PAGE, offset },
            signal,
          ),
        queryKey: queryKeys.tickets(orgSlug, { ...params, group, offset }),
        refetchInterval: LIST_POLL_MS,
      }
    }),
  })
}

/**
 * A change to a task, then a refresh of the task, its events, the
 * inbox, and the waiting count.
 */
export function useTicketMutation<T>(
  orgSlug: string,
  shortId: string,
  mutationFn: (value: T) => Promise<unknown>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSettled: () =>
      Promise.all(
        [
          queryKeys.ticket(orgSlug, shortId),
          queryKeys.ticketEvents(orgSlug, shortId),
          queryKeys.tickets(orgSlug),
          queryKeys.ticketsWaiting(orgSlug),
        ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ),
  })
}

export function useTicketProjects(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => listTicketProjects(orgSlug, shortId, signal),
    queryKey: queryKeys.ticketProjects(orgSlug, shortId),
  })
}

/**
 * A change to the relations of tasks. It writes events on each task in
 * it, so the relations, the events, and the tasks of the org read again.
 */
export function useTicketRelationMutation<T>(
  orgSlug: string,
  mutationFn: (value: T) => Promise<unknown>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSettled: () =>
      Promise.all(
        [
          queryKeys.ticketRelations(orgSlug),
          queryKeys.ticketProjects(orgSlug),
          queryKeys.ticketEvents(orgSlug),
          queryKeys.ticket(orgSlug),
        ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ),
  })
}

export function useTicketRelations(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => getTicketRelations(orgSlug, shortId, signal),
    queryKey: queryKeys.ticketRelations(orgSlug, shortId),
  })
}

export function useTickets(orgSlug: string, params: TicketListParams) {
  return useQuery({
    queryFn: ({ signal }) => listTickets(orgSlug, params, signal),
    queryKey: queryKeys.tickets(orgSlug, params),
    refetchInterval: LIST_POLL_MS,
  })
}

/**
 * The number of tasks in the org that wait on a person (not closed, a
 * request open), for the badge (O1).
 */
export function useWaitingTaskCount(orgSlug: string | undefined) {
  const canRead = useHasPermission('ticket:read', orgSlug)
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => countWaitingTickets(orgSlug!, signal),
    queryKey: queryKeys.ticketsWaiting(orgSlug ?? ''),
    refetchInterval: LIST_POLL_MS,
    select: (data) => data.count,
  })
}
