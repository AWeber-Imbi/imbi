import { describe, expect, it } from 'vitest'

import { insertReference, referenceGroups } from '../references'
import type { WorkflowGraph } from '../types'
import { node, stepType, TYPES } from './fixtures'

const types = {
  ...TYPES,
  agent: stepType({
    category: 'agent',
    output_schema: {
      properties: {
        outcome: { type: 'string' },
        reason: { anyOf: [{ type: 'string' }, { type: 'null' }] },
        result: { anyOf: [{ type: 'object' }, { type: 'null' }] },
        task_id: { type: 'string' },
      },
    },
    ports: ['Succeeded', 'Failed'],
    type: 'agent',
  }),
  model_decision: {
    ...TYPES.model_decision,
    output_schema: {
      properties: {
        choice: { type: 'string' },
        probability: { type: 'number' },
      },
    },
  },
  webhook: stepType({
    category: 'trigger',
    output_schema: {
      properties: {
        payload: { type: 'object' },
        project: { anyOf: [{ type: 'string' }, { type: 'null' }] },
      },
    },
    trigger: true,
    type: 'webhook',
  }),
}

// start → triage → decide ─(Yes)→ fix → report
//                         └─(No)──────→ report
const GRAPH: WorkflowGraph = {
  edges: [
    { port: 0, source: 'start', target: 'triage' },
    { port: 0, source: 'triage', target: 'decide' },
    { port: 0, source: 'decide', target: 'fix' },
    { port: 1, source: 'decide', target: 'report' },
    { port: 0, source: 'fix', target: 'report' },
  ],
  nodes: [
    node({
      id: 'start',
      key: 'start',
      params: { inputs: [{ name: 'service', type: 'string' }] },
      title: 'Start',
      type: 'manual',
    }),
    node({
      id: 'triage',
      key: 'triage',
      params: {
        output_fields: [
          { name: 'risk', type: 'string' },
          {
            fields: [{ name: 'team', type: 'string' }],
            name: 'owner',
            required: false,
            type: 'object',
          },
          { items: 'object', name: 'rows', type: 'array' },
        ],
      },
      title: 'Triage',
      type: 'agent',
    }),
    node({
      id: 'decide',
      key: 'decide',
      title: 'Decide',
      type: 'model_decision',
    }),
    node({ id: 'fix', key: 'fix', title: 'Fix', type: 'deploy' }),
    node({ id: 'report', key: 'report', title: 'Report' }),
  ],
}

describe('referenceGroups', () => {
  it('lists every earlier step, nearest first, then the trigger', () => {
    const groups = referenceGroups(GRAPH, types, 'report')
    expect(groups.map((group) => [group.key, group.mayNotRun])).toEqual([
      ['decide', false],
      ['fix', true],
      ['triage', false],
      ['trigger', false],
    ])
  })

  it("lists a step's output schema and its type", () => {
    const [decide] = referenceGroups(GRAPH, types, 'report')
    expect(decide.references).toEqual([
      { path: 'decide.choice', type: 'string' },
      { path: 'decide.probability', type: 'number' },
    ])
  })

  it("expands an agent step's result into its output fields", () => {
    const triage = referenceGroups(GRAPH, types, 'decide')[0]
    expect(triage.references).toEqual([
      { path: 'triage.outcome', type: 'string' },
      { path: 'triage.reason', type: 'string | null' },
      { path: 'triage.result', type: 'object | null' },
      { path: 'triage.result.risk', type: 'string' },
      { path: 'triage.result.owner', type: 'object | null' },
      { path: 'triage.result.owner.team', type: 'string' },
      { path: 'triage.result.rows', type: 'array<object>' },
      { path: 'triage.task_id', type: 'string' },
    ])
  })

  it("makes the result fields nullable after an agent's Failed port", () => {
    const graph: WorkflowGraph = {
      ...GRAPH,
      edges: [
        ...GRAPH.edges,
        { port: 1, source: 'triage', target: 'alert' },
        { port: 0, source: 'alert', target: 'page' },
      ],
      nodes: [
        ...GRAPH.nodes,
        node({ id: 'alert', key: 'alert', title: 'Alert' }),
        node({ id: 'page', key: 'page', title: 'Page' }),
      ],
    }
    const triage = referenceGroups(graph, types, 'page').find(
      (group) => group.key === 'triage',
    )
    expect(triage?.references).toContainEqual({
      path: 'triage.result.risk',
      type: 'string | null',
    })
    expect(triage?.references).toContainEqual({
      path: 'triage.result.owner.team',
      type: 'string | null',
    })
    expect(referenceGroups(GRAPH, types, 'report')).toContainEqual(
      expect.objectContaining({
        key: 'triage',
        references: expect.arrayContaining([
          { path: 'triage.result.risk', type: 'string' },
        ]),
      }),
    )
  })

  it("lists a manual trigger's inputs and other triggers' output", () => {
    const graph: WorkflowGraph = {
      edges: [
        { port: 0, source: 'start', target: 'report' },
        { port: 0, source: 'hook', target: 'report' },
      ],
      nodes: [
        ...GRAPH.nodes,
        node({ id: 'hook', key: 'hook', type: 'webhook' }),
      ],
    }
    expect(referenceGroups(graph, types, 'report')).toEqual([
      {
        key: 'trigger',
        mayNotRun: false,
        references: [
          { path: 'trigger.service', type: 'string' },
          { path: 'trigger.payload', type: 'object' },
          { path: 'trigger.project', type: 'string | null' },
        ],
        title: 'Trigger',
      },
    ])
  })

  it('names the trigger alone when its fields are unknown', () => {
    const graph: WorkflowGraph = {
      edges: [{ port: 0, source: 'a', target: 'b' }],
      nodes: [node({ id: 'a', type: 'manual' }), node({ id: 'b', key: 'b' })],
    }
    expect(referenceGroups(graph, types, 'b')[0].references).toEqual([
      { path: 'trigger', type: 'object' },
    ])
  })

  it('has nothing for a node with no earlier steps', () => {
    expect(referenceGroups(GRAPH, types, 'start')).toEqual([])
  })
})

describe('insertReference', () => {
  it('replaces the selection and puts the caret after the reference', () => {
    expect(insertReference('Hi there', 'trigger.user', [3, 8])).toEqual({
      caret: 21,
      value: 'Hi {{ trigger.user }}',
    })
  })

  it('appends when the field has no caret', () => {
    expect(insertReference('Hi ', 'trigger.user', null)).toEqual({
      caret: 21,
      value: 'Hi {{ trigger.user }}',
    })
  })
})
