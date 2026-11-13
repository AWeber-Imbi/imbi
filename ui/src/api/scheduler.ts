import { ApiClient } from '@/api/client'
import type { PatchOperation } from '@/types'
import type {
  DryRun,
  ScheduledRun,
  ScheduledTask,
  ScheduledTaskCreate,
} from '@/types/scheduler'

// imbi-scheduler is on the same origin as the UI: Caddy strips /scheduler
// and the scheduler mounts its routes under /api. It takes the same bearer
// token as imbi-api.
// ponytail: fixed same-origin path like api/assistant.ts; inject it next to
// IMBI_API_URL if the UI ever runs cross-origin from the scheduler.
const client = new ApiClient('/scheduler/api')

const task = (slug: string) => `/tasks/${encodeURIComponent(slug)}`

export const listScheduledTasks = (signal?: AbortSignal) =>
  client.get<ScheduledTask[]>('/tasks', undefined, signal)

export const getScheduledTask = (slug: string, signal?: AbortSignal) =>
  client.get<ScheduledTask>(task(slug), undefined, signal)

export const createScheduledTask = (body: ScheduledTaskCreate) =>
  client.post<ScheduledTask>('/tasks', body)

export const patchScheduledTask = (slug: string, body: PatchOperation[]) =>
  client.patch<ScheduledTask>(task(slug), body)

export const deleteScheduledTask = (slug: string) =>
  client.delete<void>(task(slug))

export const pauseScheduledTask = (slug: string) =>
  client.post<ScheduledTask>(`${task(slug)}/pause`)

export const resumeScheduledTask = (slug: string) =>
  client.post<ScheduledTask>(`${task(slug)}/resume`)

export const runScheduledTask = (slug: string) =>
  client.post<ScheduledRun>(`${task(slug)}/run`)

export const dryRunScheduledTask = (slug: string, signal?: AbortSignal) =>
  client.post<DryRun>(`${task(slug)}/dry-run`, undefined, signal)

export const listScheduledTaskRuns = (
  slug: string,
  limit: number,
  signal?: AbortSignal,
) => client.get<ScheduledRun[]>(`${task(slug)}/runs`, { limit }, signal)
