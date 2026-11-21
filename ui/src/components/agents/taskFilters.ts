import { useCallback, useEffect, useMemo, useRef } from 'react'

import { useLocation, useNavigate, useNavigationType } from 'react-router-dom'

import type { TicketStatus } from '@/types'

/** The assignee value of "my tasks": the API's `mine`. */
export const ME = 'me'

export const TASK_STATES: { label: string; value: TicketStatus }[] = [
  { label: 'Needs input', value: 'blocked' },
  { label: 'Running', value: 'running' },
  { label: 'Paused', value: 'paused' },
  { label: 'Queued', value: 'queued' },
  { label: 'Closed', value: 'closed' },
]

/** A custom field that the list can filter on, and its values. */
export interface FilterField {
  label: string
  name: string
  values: string[]
}

export interface TaskFilters {
  agents: string[]
  assignees: string[]
  /** Custom fields: tickets with one of the values of each field. */
  fields: Record<string, string[]>
  /** Tickets with every one of these labels. */
  labels: string[]
  states: TicketStatus[]
  teams: string[]
}

export const NO_FILTERS: TaskFilters = {
  agents: [],
  assignees: [],
  fields: {},
  labels: [],
  states: [],
  teams: [],
}

export function activeCount(filters: TaskFilters): number {
  return [
    filters.agents,
    filters.assignees,
    filters.labels,
    filters.states,
    filters.teams,
    ...Object.values(filters.fields),
  ].filter((values) => values.length > 0).length
}

/** The custom field filters as the API takes them: `field:in:a,b`. */
export function fieldFilters(filters: TaskFilters): string[] {
  return Object.entries(filters.fields)
    .filter(([, values]) => values.length > 0)
    .map(([name, values]) => `${name}:in:${values.join(',')}`)
}

export function readFilters(search: string): TaskFilters {
  const params = new URLSearchParams(search)
  const states = new Set(params.getAll('state'))
  const fields: Record<string, string[]> = {}
  for (const filter of params.getAll('filter')) {
    const [name, op, ...rest] = filter.split(':')
    if (name && (op === 'in' || op === 'eq'))
      fields[name] = unique(rest.join(':').split(','))
  }
  return {
    agents: unique(params.getAll('agent')),
    assignees: unique(params.getAll('assignee')),
    fields,
    labels: unique(params.getAll('label')),
    states: TASK_STATES.map((s) => s.value).filter((s) => states.has(s)),
    teams: unique(params.getAll('team')),
  }
}

const KEYS = ['agent', 'assignee', 'filter', 'label', 'state', 'team']

/**
 * The inbox filters, which live in the address, so a link, Back, and
 * Forward all change them. A link or a tab in the task pane goes to a
 * path with no filter query; that keeps the last filters and puts them
 * back in the address. Back or Forward to such a path clears them.
 */
export function useTaskFilters() {
  const { hash, pathname, search, state } = useLocation()
  const navigate = useNavigate()
  const navigation = useNavigationType()
  const last = useRef(readFilters(search))
  const inAddress = hasFilters(search) || navigation === 'POP'
  const filters = useMemo(
    () => (inAddress ? readFilters(search) : last.current),
    [inAddress, search],
  )
  useEffect(() => {
    last.current = filters
  }, [filters])
  const go = useCallback(
    (next: TaskFilters) =>
      navigate(
        { hash, pathname, search: writeFilters(search, next) },
        { replace: true, state },
      ),
    [hash, navigate, pathname, search, state],
  )
  useEffect(() => {
    if (!inAddress && activeCount(filters) > 0) go(filters)
  }, [filters, go, inAddress])
  const setFilters = useCallback(
    (next: TaskFilters) => {
      last.current = next
      go(next)
    },
    [go],
  )
  return [filters, setFilters] as const
}

export function writeFilters(search: string, filters: TaskFilters): string {
  const params = new URLSearchParams(search)
  for (const key of KEYS) params.delete(key)
  for (const state of filters.states) params.append('state', state)
  for (const agent of filters.agents) params.append('agent', agent)
  for (const assignee of filters.assignees) params.append('assignee', assignee)
  for (const label of filters.labels) params.append('label', label)
  for (const team of filters.teams) params.append('team', team)
  for (const filter of fieldFilters(filters)) params.append('filter', filter)
  const text = params.toString()
  return text ? `?${text}` : ''
}

function hasFilters(search: string): boolean {
  const params = new URLSearchParams(search)
  return KEYS.some((key) => params.has(key))
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))]
}
