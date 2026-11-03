// Parser for the copilot's server-sent events. Network chunks do not line up with events, so a
// line split across two reads is held until the rest arrives.

export type CopilotEvent =
  | { type: 'text'; content: string }
  | { type: 'action'; action: unknown }
  | { type: 'error'; content: string }
  | { type: 'done' }

function toEvent(raw: string): CopilotEvent | null {
  let data: unknown
  try {
    data = JSON.parse(raw)
  } catch {
    return null
  }
  if (typeof data !== 'object' || data === null) return null
  const event = data as Record<string, unknown>
  if (event.type === 'text' && typeof event.content === 'string') return { type: 'text', content: event.content }
  if (event.type === 'action' && 'action' in event) return { type: 'action', action: event.action }
  if (event.type === 'error') return { type: 'error', content: typeof event.content === 'string' ? event.content : '' }
  if (event.type === 'done') return { type: 'done' }
  return null
}

export function createSseParser() {
  let buffer = ''

  const read = (lines: string[]) => {
    const events: CopilotEvent[] = []
    for (const line of lines) {
      if (!line.startsWith('data:')) continue
      const raw = line.slice(5).trim()
      if (!raw) continue
      const event = toEvent(raw)
      if (event) events.push(event)
    }
    return events
  }

  return {
    /** Add a decoded chunk; returns the events completed by it. */
    push(chunk: string): CopilotEvent[] {
      buffer += chunk
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      return read(lines)
    },
    /** Read whatever is left once the stream has ended. */
    flush(): CopilotEvent[] {
      const rest = buffer
      buffer = ''
      return read([rest])
    },
  }
}
