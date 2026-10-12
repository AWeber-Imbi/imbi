import { describe, expect, it } from 'vitest'

import {
  addNode,
  canConnect,
  createNode,
  duplicateNode,
  fitView,
  keyFromTitle,
  outPoint,
  placeNew,
  removeBranch,
  removeNode,
  toCanvas,
  uniqueKey,
  zoomAt,
} from '../graph'
import type { WorkflowGraph } from '../types'
import { node, STEP_TYPES, TYPES } from './fixtures'

const [manual, wait, decision] = STEP_TYPES

describe('createNode', () => {
  it('takes defaults from the schema and a key from the label', () => {
    const n = createNode({ edges: [], nodes: [] }, wait, { x: 33, y: 9 })
    expect(n.params).toEqual({ duration_seconds: 600 })
    expect(n.key).toBe('wait')
    expect(n.position).toEqual({ x: 40, y: 0 })
  })

  it('gives a branching type two branches', () => {
    const n = createNode({ edges: [], nodes: [] }, decision, { x: 0, y: 0 })
    expect(n.params.branches).toEqual(['Yes', 'No'])
  })

  it('suffixes the key when another node has it', () => {
    const graph: WorkflowGraph = {
      edges: [],
      nodes: [node({ id: 'a', key: 'wait' }), node({ id: 'b', key: 'wait_2' })],
    }
    expect(createNode(graph, wait, { x: 0, y: 0 }).key).toBe('wait_3')
  })
})

describe('keys', () => {
  it('slugs a title and starts it with a letter', () => {
    expect(keyFromTitle('Let traffic settle!')).toBe('let_traffic_settle')
    expect(keyFromTitle('2nd deploy')).toBe('step_2nd_deploy')
    expect(keyFromTitle('***')).toBe('step')
  })

  it('ignores the node being renamed', () => {
    const graph = { edges: [], nodes: [node({ id: 'a', key: 'wait' })] }
    expect(uniqueKey(graph, 'wait', 'a')).toBe('wait')
    expect(uniqueKey(graph, 'wait')).toBe('wait_2')
  })

  it('gives a duplicate its own key and id', () => {
    const graph = { edges: [], nodes: [node({ id: 'a', title: 'Settle' })] }
    const { node: copy } = duplicateNode(graph, 'a')
    expect(copy?.id).not.toBe('a')
    expect(copy?.title).toBe('Settle copy')
    expect(copy?.key).toBe('settle_copy')
  })
})

describe('connections', () => {
  const graph: WorkflowGraph = {
    edges: [{ port: 0, source: 'w', target: 'd' }],
    nodes: [
      node({ id: 't', type: 'manual' }),
      node({ id: 'w' }),
      node({ id: 'd', type: 'deploy' }),
    ],
  }

  it('refuses edges into a trigger, into the source, and duplicates', () => {
    expect(
      canConnect(graph, TYPES, { port: 0, source: 'w', target: 't' }),
    ).toBe(false)
    expect(
      canConnect(graph, TYPES, { port: 0, source: 'w', target: 'w' }),
    ).toBe(false)
    expect(
      canConnect(graph, TYPES, { port: 0, source: 'w', target: 'd' }),
    ).toBe(false)
    expect(
      canConnect(graph, TYPES, { port: 0, source: 't', target: 'w' }),
    ).toBe(true)
  })

  it('connects a new node to the output it was dropped from', () => {
    const n = createNode(graph, wait, { x: 0, y: 0 })
    const next = addNode(graph, n, TYPES, { port: 1, source: 'd' })
    expect(next.edges).toContainEqual({ port: 1, source: 'd', target: n.id })
  })

  it('does not connect into a new trigger', () => {
    const n = createNode(graph, manual, { x: 0, y: 0 })
    expect(
      addNode(graph, n, TYPES, { port: 0, source: 'w' }).edges,
    ).toHaveLength(1)
  })

  it('removes the edges of a deleted node', () => {
    const next = removeNode(graph, 'w')
    expect(next.nodes.map((n) => n.id)).toEqual(['t', 'd'])
    expect(next.edges).toEqual([])
  })
})

describe('removeBranch', () => {
  it('drops the branch edges and moves higher ports down', () => {
    const graph: WorkflowGraph = {
      edges: [
        { port: 0, source: 'm', target: 'a' },
        { port: 1, source: 'm', target: 'b' },
        { port: 2, source: 'm', target: 'c' },
        { port: 2, source: 'x', target: 'c' },
      ],
      nodes: [
        node({
          id: 'm',
          params: { branches: ['Roll back', 'Fix forward', 'Ask'] },
          type: 'model_decision',
        }),
      ],
    }
    const next = removeBranch(graph, 'm', 1)
    expect(next.nodes[0].params.branches).toEqual(['Roll back', 'Ask'])
    expect(next.edges).toEqual([
      { port: 0, source: 'm', target: 'a' },
      { port: 1, source: 'm', target: 'c' },
      { port: 2, source: 'x', target: 'c' },
    ])
  })
})

describe('canvas math', () => {
  it('keeps the point under the cursor still when it zooms', () => {
    const view = { x: 100, y: 50, zoom: 1 }
    const at = { x: 400, y: 300 }
    const before = toCanvas(at, { x: 0, y: 0 }, view)
    const after = toCanvas(at, { x: 0, y: 0 }, zoomAt(view, at, 1.5))
    expect(after.x).toBeCloseTo(before.x)
    expect(after.y).toBeCloseTo(before.y)
  })

  it('clamps the zoom', () => {
    expect(zoomAt({ x: 0, y: 0, zoom: 1 }, { x: 0, y: 0 }, 10).zoom).toBe(2)
    expect(zoomAt({ x: 0, y: 0, zoom: 1 }, { x: 0, y: 0 }, 0.01).zoom).toBe(
      0.25,
    )
  })

  it('fits the graph without zooming past 100%', () => {
    const graph = { edges: [], nodes: [node({ position: { x: 200, y: 100 } })] }
    const view = fitView(graph, TYPES, 1000, 600)
    expect(view.zoom).toBe(1)
    // The node's centre lands on the viewport's centre.
    expect(view.x + (200 + 124)).toBe(500)
  })

  it('puts labelled ports in rows under the summary', () => {
    const d = node({ type: 'deploy' })
    expect(outPoint(d, ['Succeeded', 'Failed'], 1)).toEqual({ x: 248, y: 141 })
    expect(outPoint(node(), [''], 0)).toEqual({ x: 248, y: 28 })
  })

  it('places a palette step after the first free port of the selection', () => {
    const graph: WorkflowGraph = {
      edges: [{ port: 0, source: 'd', target: 'x' }],
      nodes: [node({ id: 'd', type: 'deploy' })],
    }
    const spot = placeNew(graph, TYPES, { x: 0, y: 0 }, graph.nodes[0], false)
    expect(spot.from).toEqual({ port: 1, source: 'd' })
    expect(spot.position.x).toBe(320)
  })
})
