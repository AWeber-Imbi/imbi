import { describe, expect, it } from 'vitest'

import { event } from '@/components/agents/__tests__/taskFixtures'
import { mergeEvents } from '@/components/agents/taskQueries'

import { readServerSentEvents, type ServerSentEvent } from '../sse'

async function read(...chunks: string[]): Promise<ServerSentEvent[]> {
  const events: ServerSentEvent[] = []
  await readServerSentEvents(response(...chunks), (e) => events.push(e))
  return events
}

function response(...chunks: string[]): Response {
  const encoder = new TextEncoder()
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
        controller.close()
      },
    }),
  )
}

describe('readServerSentEvents', () => {
  it('parses events split across chunks and skips comments', async () => {
    expect(
      await read(
        ': ping\n\nid: 4\nevent: task_',
        'event\ndata: {"seq":4}\n\n',
        'id: 5\r\nevent: task_event\r\ndata: {"seq"\r\ndata: :5}\r\n\r\n',
      ),
    ).toEqual([
      { data: '{"seq":4}', event: 'task_event', id: '4' },
      { data: '{"seq"\n:5}', event: 'task_event', id: '5' },
    ])
  })

  it('drops an event the body cuts off', async () => {
    expect(await read('id: 1\ndata: x\n\nid: 2\ndata: y')).toEqual([
      { data: 'x', event: 'message', id: '1' },
    ])
  })
})

describe('mergeEvents', () => {
  it('adds new seqs in order, once each', () => {
    const have = [event(1, 'a'), event(3, 'c')]
    expect(
      mergeEvents(have, [event(3, 'c'), event(2, 'b'), event(2, 'b')]).map(
        (e) => e.seq,
      ),
    ).toEqual([1, 2, 3])
  })

  it('returns the same array when nothing is new', () => {
    const have = [event(1, 'a')]
    expect(mergeEvents(have, [event(1, 'a')])).toBe(have)
  })
})
