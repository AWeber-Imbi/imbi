/** One server-sent event. A comment (`: ping`) is not an event. */
export interface ServerSentEvent {
  data: string
  event: string
  id?: string
}

/**
 * Read the server-sent events of `response` until the body ends, and
 * call `onEvent` for each. `fetch`, not `EventSource`, because the API
 * takes the access token in the `Authorization` header.
 */
export async function readServerSentEvents(
  response: Response,
  onEvent: (event: ServerSentEvent) => void,
): Promise<void> {
  const reader = response.body?.getReader()
  if (!reader) return
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n?/g, '\n')
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() ?? ''
      for (const block of blocks) {
        const event = parseBlock(block)
        if (event) onEvent(event)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

function parseBlock(block: string): null | ServerSentEvent {
  const data: string[] = []
  let event = 'message'
  let id: string | undefined
  for (const line of block.split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon < 0 ? line : line.slice(0, colon)
    let value = colon < 0 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'data') data.push(value)
    else if (field === 'event') event = value
    else if (field === 'id') id = value
  }
  if (!data.length) return null
  return { data: data.join('\n'), event, id }
}
