import { describe, expect, it } from 'vitest'

import { formatDuration, manualTrigger, runResults, testResults } from '../runs'
import { node, TYPES } from './fixtures'

describe('runs', () => {
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
