import { useEffect, useRef } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import {
  type AgentTaskListParams,
  countWaitingAgentTasks,
  getAgentTask,
  listAgentTaskEvents,
  listAgentTasks,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentTask, AgentTaskEvent } from '@/types'

/** How often a live task reads new events (O4). */
export const EVENT_POLL_MS = 3000

/** How often the inbox and the "waiting on you" count refresh. */
const LIST_POLL_MS = 15_000

const EVENT_PAGE = 500

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

export function useAgentTask(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => getAgentTask(orgSlug, shortId, signal),
    queryKey: queryKeys.agentTask(orgSlug, shortId),
  })
}

/**
 * The events of a task. Each refetch reads only the events after the
 * newest one in the cache and appends them, so polling is cheap and the
 * page never reloads. Polls while `live`.
 */
export function useAgentTaskEvents(
  orgSlug: string,
  shortId: string,
  live: boolean,
) {
  const queryClient = useQueryClient()
  const queryKey = queryKeys.agentTaskEvents(orgSlug, shortId)
  const query = useQuery({
    queryFn: async ({ signal }) => {
      const have = queryClient.getQueryData<AgentTaskEvent[]>(queryKey) ?? []
      const events = [...have]
      for (;;) {
        const page = await listAgentTaskEvents(
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
  // task, the inbox, and the waiting count read it again. Before the
  // first event read, the reference is the `last_seq` of the cached
  // task, because the task can change between the two reads.
  const lastSeq = query.data?.[query.data.length - 1]?.seq ?? 0
  const seenSeq = useRef(0)
  useEffect(() => {
    const taskKey = queryKeys.agentTask(orgSlug, shortId)
    const base =
      seenSeq.current ||
      (queryClient.getQueryData<AgentTask>(taskKey)?.last_seq ?? lastSeq)
    if (lastSeq > base) {
      for (const key of [
        taskKey,
        queryKeys.agentTasks(orgSlug),
        queryKeys.agentTasksWaiting(orgSlug),
      ])
        void queryClient.invalidateQueries({ queryKey: key })
    }
    seenSeq.current = lastSeq
  }, [lastSeq, orgSlug, shortId, queryClient])
  return query
}

/**
 * A change to a task, then a refresh of the task, its events, the
 * inbox, and the waiting count.
 */
export function useAgentTaskMutation<T>(
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
          queryKeys.agentTask(orgSlug, shortId),
          queryKeys.agentTaskEvents(orgSlug, shortId),
          queryKeys.agentTasks(orgSlug),
          queryKeys.agentTasksWaiting(orgSlug),
        ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ),
  })
}

export function useAgentTasks(orgSlug: string, params: AgentTaskListParams) {
  return useQuery({
    queryFn: ({ signal }) => listAgentTasks(orgSlug, params, signal),
    queryKey: queryKeys.agentTasks(orgSlug, params),
    refetchInterval: LIST_POLL_MS,
  })
}

/**
 * The number of tasks in the org that wait on a person (not closed, a
 * request open), for the badge (O1).
 */
export function useWaitingTaskCount(orgSlug: string | undefined) {
  const canRead = useHasPermission('agent_task:read')
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => countWaitingAgentTasks(orgSlug!, signal),
    queryKey: queryKeys.agentTasksWaiting(orgSlug ?? ''),
    refetchInterval: LIST_POLL_MS,
    select: (data) => data.count,
  })
}
