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
  type AgentTaskListParams,
  countAgentTasks,
  countWaitingAgentTasks,
  getAgentTask,
  getAgentTaskRelations,
  listAgentTaskEvents,
  listAgentTaskProjects,
  listAgentTasks,
  replyAgentTask,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentTask, AgentTaskEvent } from '@/types'

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

export function useAgentTask(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => getAgentTask(orgSlug, shortId, signal),
    queryKey: queryKeys.agentTask(orgSlug, shortId),
  })
}

/**
 * The number of tasks in each inbox group. A change of filters keeps
 * the old counts until the new ones come, so the list does not jump.
 */
export function useAgentTaskCounts(
  orgSlug: string,
  params: AgentTaskListParams,
) {
  return useQuery({
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => countAgentTasks(orgSlug, params, signal),
    queryKey: queryKeys.agentTasks(orgSlug, { ...params, counts: true }),
    refetchInterval: LIST_POLL_MS,
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
    const taskKey = queryKeys.agentTask(orgSlug, shortId)
    const previousSeq = seenSeq.current
    const base =
      previousSeq ||
      (queryClient.getQueryData<AgentTask>(taskKey)?.last_seq ?? lastSeq)
    const keys: QueryKey[] = []
    if (lastSeq > base)
      keys.push(
        taskKey,
        queryKeys.agentTasks(orgSlug),
        queryKeys.agentTasksWaiting(orgSlug),
      )
    if (data?.some((e) => e.seq > previousSeq && RELATION_EVENTS.has(e.type)))
      keys.push(
        queryKeys.agentTaskRelations(orgSlug, shortId),
        queryKeys.agentTaskProjects(orgSlug, shortId),
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
export function useAgentTaskGroupPages(
  orgSlug: string,
  params: AgentTaskListParams,
  pages: string[],
) {
  return useQueries({
    queries: pages.map((name) => {
      const [group, page] = name.split(':') as [
        NonNullable<AgentTaskListParams['group']>,
        string,
      ]
      const offset = Number(page) * TASK_PAGE
      return {
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          listAgentTasks(
            orgSlug,
            { ...params, group, limit: TASK_PAGE, offset },
            signal,
          ),
        queryKey: queryKeys.agentTasks(orgSlug, { ...params, group, offset }),
        refetchInterval: LIST_POLL_MS,
      }
    }),
  })
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

export function useAgentTaskProjects(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => listAgentTaskProjects(orgSlug, shortId, signal),
    queryKey: queryKeys.agentTaskProjects(orgSlug, shortId),
  })
}

/**
 * A change to the relations of tasks. It writes events on each task in
 * it, so the relations, the events, and the tasks of the org read again.
 */
export function useAgentTaskRelationMutation<T>(
  orgSlug: string,
  mutationFn: (value: T) => Promise<unknown>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSettled: () =>
      Promise.all(
        [
          queryKeys.agentTaskRelations(orgSlug),
          queryKeys.agentTaskProjects(orgSlug),
          queryKeys.agentTaskEvents(orgSlug),
          queryKeys.agentTask(orgSlug),
        ].map((queryKey) => queryClient.invalidateQueries({ queryKey })),
      ),
  })
}

export function useAgentTaskRelations(orgSlug: string, shortId: string) {
  return useQuery({
    queryFn: ({ signal }) => getAgentTaskRelations(orgSlug, shortId, signal),
    queryKey: queryKeys.agentTaskRelations(orgSlug, shortId),
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
/**
 * The reply mutation of a task, owned above the views so a pending reply
 * stays pending when the composer remounts.
 */
export function useTaskReply(orgSlug: string, shortId: string) {
  return useAgentTaskMutation(
    orgSlug,
    shortId,
    ({ hold, text }: { hold: boolean; text: string }) =>
      replyAgentTask(orgSlug, shortId, text.trim(), hold),
  )
}

export function useWaitingTaskCount(orgSlug: string | undefined) {
  const canRead = useHasPermission('agent_task:read', orgSlug)
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => countWaitingAgentTasks(orgSlug!, signal),
    queryKey: queryKeys.agentTasksWaiting(orgSlug ?? ''),
    refetchInterval: LIST_POLL_MS,
    select: (data) => data.count,
  })
}
