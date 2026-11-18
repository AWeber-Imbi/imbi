import { useEffect, useRef, useState } from 'react'

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
  streamAgentTaskEvents,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'
import type { AgentTask, AgentTaskEvent } from '@/types'

/**
 * How often a live task reads new events (O4) while its event stream
 * is down.
 */
export const EVENT_POLL_MS = 3000

/** Backoff bounds for reconnecting the event stream of a task. */
const STREAM_RETRY_MIN_MS = 1000
const STREAM_RETRY_MAX_MS = 30_000

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
 * `have` with the events of `add` that it does not have, in seq order.
 * `have` itself when `add` has nothing new.
 */
export function mergeEvents(
  have: AgentTaskEvent[],
  add: AgentTaskEvent[],
): AgentTaskEvent[] {
  const seqs = new Set(have.map((e) => e.seq))
  const fresh: AgentTaskEvent[] = []
  for (const event of add) {
    if (seqs.has(event.seq)) continue
    seqs.add(event.seq)
    fresh.push(event)
  }
  if (!fresh.length) return have
  return [...have, ...fresh].sort((a, b) => a.seq - b.seq)
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
 * newest one in the cache and merges them in, so polling is cheap and
 * the page never reloads. After the first read, the event stream of
 * the task adds each new event to the same cache, for open and closed
 * tasks alike: a closed task can take events, and a `state.changed`
 * event reopens it. While the stream is down, a `live` task polls.
 */
export function useAgentTaskEvents(
  orgSlug: string,
  shortId: string,
  live: boolean,
) {
  const queryClient = useQueryClient()
  const queryKey = queryKeys.agentTaskEvents(orgSlug, shortId)
  const [streaming, setStreaming] = useState(false)
  const query = useQuery({
    queryFn: async ({ signal }) => {
      const have = queryClient.getQueryData<AgentTaskEvent[]>(queryKey) ?? []
      const read: AgentTaskEvent[] = []
      for (;;) {
        const page = await listAgentTaskEvents(
          orgSlug,
          shortId,
          (read[read.length - 1] ?? have[have.length - 1])?.seq ?? 0,
          EVENT_PAGE,
          signal,
        )
        read.push(...page)
        if (page.length < EVENT_PAGE) break
      }
      // The stream can add events during the read: merge into the cache
      // as it is now, not as it was.
      return mergeEvents(
        queryClient.getQueryData<AgentTaskEvent[]>(queryKey) ?? have,
        read,
      )
    },
    queryKey,
    refetchInterval: live && !streaming ? EVENT_POLL_MS : false,
  })
  useAgentTaskEventStream(orgSlug, shortId, query.isSuccess, setStreaming)
  useRefetchWhenVisible(orgSlug, shortId)
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

/** Whether the API refused the stream, so a retry cannot help. */
function refused(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    error.status >= 400 &&
    error.status < 500 &&
    error.status !== 429
  )
}

/**
 * Hold the event stream of a task open once its events are read
 * (`ready`), and merge each event into the events cache. Each connect
 * starts after the newest cached event, so a reconnect sends nothing
 * twice. After an error or an end it reconnects with backoff; a
 * refusal (4xx) stops it, and the task polls. `onConnected` says
 * whether the stream is up.
 */
function useAgentTaskEventStream(
  orgSlug: string,
  shortId: string,
  ready: boolean,
  onConnected: (connected: boolean) => void,
) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!ready) return
    const queryKey = queryKeys.agentTaskEvents(orgSlug, shortId)
    const controller = new AbortController()
    let delay = STREAM_RETRY_MIN_MS
    let timer: ReturnType<typeof setTimeout> | undefined
    const connect = () => {
      const have = queryClient.getQueryData<AgentTaskEvent[]>(queryKey) ?? []
      streamAgentTaskEvents(
        orgSlug,
        shortId,
        have[have.length - 1]?.seq ?? 0,
        {
          onEvent: (event) =>
            queryClient.setQueryData<AgentTaskEvent[]>(queryKey, (old) =>
              mergeEvents(old ?? [], [event]),
            ),
          onOpen: () => {
            delay = STREAM_RETRY_MIN_MS
            onConnected(true)
          },
        },
        controller.signal,
      )
        .then(
          () => undefined,
          (error: unknown) => error,
        )
        .then((error) => {
          if (controller.signal.aborted) return
          onConnected(false)
          if (refused(error)) return
          timer = setTimeout(connect, delay)
          delay = Math.min(delay * 2, STREAM_RETRY_MAX_MS)
        })
    }
    connect()
    return () => {
      controller.abort()
      clearTimeout(timer)
      onConnected(false)
    }
  }, [orgSlug, shortId, ready, onConnected, queryClient])
}

/**
 * Read the task and its events again when the tab becomes visible: a
 * hidden tab can miss events while its stream reconnects.
 */
function useRefetchWhenVisible(orgSlug: string, shortId: string) {
  const queryClient = useQueryClient()
  useEffect(() => {
    const onChange = () => {
      if (document.visibilityState !== 'visible') return
      for (const queryKey of [
        queryKeys.agentTask(orgSlug, shortId),
        queryKeys.agentTaskEvents(orgSlug, shortId),
      ])
        void queryClient.invalidateQueries({ queryKey })
    }
    document.addEventListener('visibilitychange', onChange)
    return () => document.removeEventListener('visibilitychange', onChange)
  }, [orgSlug, shortId, queryClient])
}
