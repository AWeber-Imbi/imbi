// imbi-scheduler API types, written by hand from
// apps/scheduler/src/imbi/scheduler/{models,triggers,runs,executor}.py.
// The scheduler is not part of api-generated.ts.

export interface ApiTarget {
  body?: null | Record<string, unknown>
  kind: 'api'
  method: HttpMethod
  organization?: null | string
  path: string
  query?: Record<string, string>
}

export interface CalendarTrigger {
  at_time: string
  days?: number
  end_at?: null | string
  kind: 'calendar'
  months?: number
  start_at?: null | string
  weeks?: number
}

export interface CronTrigger {
  expression: string
  jitter?: null | number
  kind: 'cron'
}

export interface DateTrigger {
  kind: 'date'
  run_at: string
}

export interface DryRun {
  actor_name: string
  bearer_resolved: boolean
  body: null | Record<string, unknown>
  headers: Record<string, string>
  identity_kind: string
  method: string
  principal_name: string
  query: Record<string, string>
  reason: string
  url: string
  would_run: boolean
}

export interface ExecutionPolicy {
  idempotency_key?: null | string
  max_running_instances: number
  misfire_grace_time: null | number
  retries: number
  retry_backoff: 'exponential' | 'linear' | 'none'
  timeout: number
}

export interface GatewayTarget {
  headers?: Record<string, string>
  kind: 'gateway'
  payload: Record<string, unknown>
  webhook_id: string
}

export type HttpMethod = 'DELETE' | 'GET' | 'PATCH' | 'POST' | 'PUT'

export interface IntervalTrigger {
  days?: number
  end_at?: null | string
  hours?: number
  kind: 'interval'
  minutes?: number
  seconds?: number
  start_at?: null | string
}

export interface ScheduledRun {
  attempt: number
  duration_ms: number
  error_message: string
  error_type: string
  finished_at: null | string
  fired_at: string
  http_status: number
  response_excerpt: string
  run_id: string
  state: ScheduledRunState
  task_slug: string
}

export type ScheduledRunState =
  | 'cancelled'
  | 'failed'
  | 'no_effect'
  | 'running'
  | 'skipped'
  | 'succeeded'
  | 'timed_out'

export interface ScheduledTask extends ScheduledTaskCreate {
  created_at: string
  created_by: string
  id: string
  last_run_at: null | string
  next_run_at: null | string
  updated_at: string
  updated_by: null | string
}

// The request body of POST /tasks.
export interface ScheduledTaskCreate {
  description: null | string
  enabled: boolean
  execution: ExecutionPolicy
  identity: null | TaskIdentity
  kind: 'system' | 'user'
  name: string
  organization?: null | string
  slug: string
  tags?: string[]
  target: ApiTarget | GatewayTarget
  timezone: string
  trigger: Trigger
}

export interface TaskIdentity {
  consent_id?: null | string
  kind: 'delegated_user' | 'service_account'
  scope?: string
  subject: string
}

export type Trigger =
  | CalendarTrigger
  | CronTrigger
  | DateTrigger
  | IntervalTrigger
