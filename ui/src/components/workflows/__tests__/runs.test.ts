import { describe, expect, it } from 'vitest'

import {
  duplicateOf,
  failureCauses,
  failureReason,
  formatDuration,
  manualTrigger,
  runResults,
  testResults,
  windowDays,
  windowSeconds,
  workflowFailures,
} from '../runs'
import { node, orgRun, TYPES } from './fixtures'

describe('runs', () => {
  it('takes the agent reason, then the step error, then the run error', () => {
    const run = orgRun('logzio_api_unauthorized')
    expect(failureReason(run)).toBe('logzio_api_unauthorized')
    expect(
      failureReason({
        ...run,
        failure: { ...run.failure!, error: 'ConnectError', reason: null },
      }),
    ).toBe('ConnectError')
    expect(failureReason({ ...run, error: 'timeout', failure: null })).toBe(
      'timeout',
    )
    expect(failureReason({ ...run, failure: null, status: 'timed_out' })).toBe(
      'timed_out',
    )
    expect(failureReason({ ...run, status: 'succeeded' })).toBeNull()
  })

  it('groups failed runs by reason, the most frequent first', () => {
    const runs = [
      orgRun('model_key_unavailable', { created_at: '2026-10-12T03:00:00Z' }),
      orgRun('checkout_refused', { created_at: '2026-10-12T02:00:00Z' }),
      orgRun('checkout_refused', {
        created_at: '2026-10-12T01:00:00Z',
        failure: {
          ...orgRun('').failure!,
          reason: 'checkout_refused',
          title: 'Writer',
        },
        workflow_name: 'Standards',
        workflow_slug: 'standards',
      }),
      orgRun(null, { status: 'succeeded' }),
    ]
    expect(failureCauses(runs)).toEqual([
      {
        count: 2,
        last: '2026-10-12T02:00:00Z',
        outcome: 'failed_external',
        reason: 'checkout_refused',
        steps: 'Review ×1, Writer ×1',
        workflows: ['Deploy guard', 'Standards'],
      },
      {
        count: 1,
        last: '2026-10-12T03:00:00Z',
        outcome: 'failed_external',
        reason: 'model_key_unavailable',
        steps: 'Review',
        workflows: ['Deploy guard'],
      },
    ])
    expect(workflowFailures(runs)).toEqual({
      'deploy-guard': {
        failed: 2,
        others: 1,
        top: 'model_key_unavailable',
        topCount: 1,
        total: 3,
      },
      standards: {
        failed: 1,
        others: 0,
        top: 'checkout_refused',
        topCount: 1,
        total: 1,
      },
    })
  })

  it('converts the dedupe window between days and seconds', () => {
    expect(windowDays(null)).toBe('')
    expect(windowDays(1_209_600)).toBe('14')
    expect(windowDays(43_200)).toBe('0.5')
    expect(windowSeconds('')).toBeNull()
    expect(windowSeconds('14')).toBe(1_209_600)
    expect(windowSeconds('0.5')).toBe(43_200)
    expect(windowSeconds('0')).toBeUndefined()
    expect(windowSeconds('-1')).toBeUndefined()
  })

  it('names the run that a skipped run repeats', () => {
    expect(duplicateOf({ duplicate_of: 'abc', status: 'skipped' })).toBe('abc')
    expect(duplicateOf({ duplicate_of: null, status: 'skipped' })).toBeNull()
    expect(duplicateOf({ duplicate_of: 'abc', status: 'queued' })).toBeNull()
  })

  it('formats durations', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(850)).toBe('850 ms')
    expect(formatDuration(12_000)).toBe('12 s')
    expect(formatDuration(184_000)).toBe('3 m 4 s')
    expect(formatDuration(7_500_000)).toBe('2 h 5 m')
  })

  it('names the branch a run step took', () => {
    const graph = {
      edges: [],
      nodes: [node({ id: 'd', type: 'deploy' })],
    }
    const results = runResults(
      [
        {
          attempt: 2,
          error: 'timeout',
          finished_at: '2026-10-12T00:00:05Z',
          input: null,
          node_id: 'd',
          node_key: 'deploy',
          node_type: 'deploy',
          output: null,
          port: 1,
          started_at: '2026-10-12T00:00:01Z',
          status: 'failed',
          title: 'Deploy',
        },
      ],
      graph,
      TYPES,
    )
    expect(results.d).toMatchObject({
      branch: 'Failed',
      durationMs: 4000,
      error: 'timeout',
      status: 'failed',
    })
  })

  it('marks the skipped nodes of a test run', () => {
    const results = testResults({
      skipped: ['x'],
      steps: [
        {
          key: 'a',
          node_id: 'a',
          output: { ok: true },
          port: 0,
          port_name: '',
          title: 'A',
          type: 'wait',
        },
      ],
    })
    expect(results.a).toMatchObject({ branch: null, status: 'succeeded' })
    expect(results.x.status).toBe('skipped')
  })

  it('reads the inputs of the manual trigger', () => {
    expect(manualTrigger({ edges: [], nodes: [node()] })).toBeNull()
    const trigger = manualTrigger({
      edges: [],
      nodes: [
        node({
          id: 't',
          params: {
            inputs: [{ name: 'version' }, { name: 'n', type: 'number' }],
          },
          type: 'manual',
        }),
      ],
    })
    expect(trigger).toEqual({
      id: 't',
      inputs: [
        { name: 'version', type: 'string' },
        { name: 'n', type: 'number' },
      ],
    })
  })
})
