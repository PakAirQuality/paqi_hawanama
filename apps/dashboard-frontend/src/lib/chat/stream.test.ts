import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamCopilot } from './stream'

const encoder = new TextEncoder()
const sse = (...events: object[]) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('')

function bodyOf(chunks: (string | Uint8Array)[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const c of chunks) controller.enqueue(typeof c === 'string' ? encoder.encode(c) : c)
      controller.close()
    },
  })
}

const respond = (status: number, body: BodyInit | null = null, headers: Record<string, string> = {}) =>
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(body, { status, headers }))

const run = (signal = new AbortController().signal, stallMs?: number) => {
  const text: string[] = []
  const actions: unknown[] = []
  const done = streamCopilot({
    url: '/x',
    body: { message: 'hi' },
    signal,
    stallMs,
    onText: t => text.push(t),
    onAction: a => actions.push(a),
  })
  return { done, text, actions }
}

describe('streamCopilot', () => {
  it('streams text to the end', async () => {
    respond(200, bodyOf([sse({ type: 'text', content: 'Hello ' }, { type: 'text', content: 'world' }, { type: 'done' })]))
    const { done, text } = run()
    expect(await done).toEqual({ status: 'ok' })
    expect(text).toEqual(['Hello ', 'Hello world'])
  })

  it('does not lose text when an event is split across chunks', async () => {
    const wire = sse({ type: 'text', content: 'Complete answer' }, { type: 'done' })
    respond(200, bodyOf([wire.slice(0, 20), wire.slice(20)]))
    const { done, text } = run()
    expect(await done).toEqual({ status: 'ok' })
    expect(text.at(-1)).toBe('Complete answer')
  })

  it('keeps a multi-byte character split across chunks intact', async () => {
    const bytes = encoder.encode(sse({ type: 'text', content: '141 µg/m³' }, { type: 'done' }))
    const cut = bytes.indexOf(0xc2) + 1 // the middle of "µ"
    respond(200, bodyOf([bytes.slice(0, cut), bytes.slice(cut)]))
    const { done, text } = run()
    await done
    expect(text.at(-1)).toBe('141 µg/m³')
  })

  it('passes on valid actions once and drops invalid ones', async () => {
    const zoom = { type: 'zoom_to_city', city: 'Lahore' }
    respond(200, bodyOf([sse(
      { type: 'text', content: 'See map' },
      { type: 'action', action: zoom },
      { type: 'action', action: zoom },
      { type: 'action', action: { type: 'drop_tables' } },
      { type: 'done' },
    )]))
    const { done, actions } = run()
    await done
    expect(actions).toEqual([zoom])
  })

  it('sends the request as JSON and honours the abort signal', async () => {
    const fetchSpy = respond(200, bodyOf([sse({ type: 'text', content: 'x' }, { type: 'done' })]))
    await run().done
    const [url, init] = fetchSpy.mock.calls[0]
    expect(url).toBe('/x')
    expect(init).toMatchObject({ method: 'POST', body: '{"message":"hi"}' })
    expect(init?.signal).toBeInstanceOf(AbortSignal)
  })

  it.each([
    ["the per-visitor daily limit", "You have reached today's limit for the assistant; please try again tomorrow.", '3600'],
    ['the global daily limit', 'The assistant has reached its daily limit; please try again tomorrow.', '3600'],
  ])('treats %s as final', async (_, detail, wait) => {
    respond(429, JSON.stringify({ detail }), { 'Retry-After': wait })
    expect(await run().done).toEqual({ status: 'limit', message: detail })
  })

  it('treats the per-minute limit as temporary', async () => {
    respond(429, JSON.stringify({ detail: 'Too many requests; slow down and retry in a minute.' }), { 'Retry-After': '60' })
    expect((await run().done).status).toBe('busy')
  })

  it('reports a service outage', async () => {
    respond(503, JSON.stringify({ detail: 'The assistant is temporarily unavailable.' }))
    expect(await run().done).toEqual({ status: 'unavailable', message: 'The assistant is temporarily unavailable.' })
  })

  it('copes with an error page that is not JSON', async () => {
    respond(503, '<html>Bad gateway</html>')
    expect((await run().done).status).toBe('unavailable')
  })

  it.each([400, 404, 422, 500])('reports HTTP %i as a failure without leaking details', async status => {
    respond(status, JSON.stringify({ detail: 'stack trace here' }))
    const outcome = await run().done
    expect(outcome.status).toBe('error')
    expect(JSON.stringify(outcome)).not.toContain('stack trace')
  })

  it('reports a network failure', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'))
    expect((await run().done).status).toBe('error')
  })

  it('keeps partial text when the server reports an error mid-answer', async () => {
    respond(200, bodyOf([sse({ type: 'text', content: 'Half an ans' }, { type: 'error', content: 'An internal error occurred.' }, { type: 'done' })]))
    const { done, text } = run()
    expect((await done).status).toBe('error')
    expect(text).toEqual(['Half an ans'])
  })

  it('treats a stream that ends without done as interrupted', async () => {
    respond(200, bodyOf([sse({ type: 'text', content: 'Half' })]))
    expect((await run().done).status).toBe('error')
  })

  it('treats an answer with no words as a failure', async () => {
    respond(200, bodyOf([sse({ type: 'done' })]))
    expect((await run().done).status).toBe('error')
  })

  it('returns stopped straight away if already aborted', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch')
    const controller = new AbortController()
    controller.abort()
    expect(await run(controller.signal).done).toEqual({ status: 'stopped' })
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  describe('with a request that hangs', () => {
    beforeEach(() => {
      vi.useFakeTimers()
      vi.spyOn(globalThis, 'fetch').mockImplementation((_, init) => new Promise((_, reject) => {
        init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      }))
    })
    afterEach(() => { vi.useRealTimers() })

    it('stops when the person presses Stop', async () => {
      const controller = new AbortController()
      const { done } = run(controller.signal)
      controller.abort()
      expect(await done).toEqual({ status: 'stopped' })
    })

    it('gives up after a long silence', async () => {
      const { done } = run(undefined, 5000)
      await vi.advanceTimersByTimeAsync(5001)
      expect((await done).status).toBe('error')
    })
  })
})
