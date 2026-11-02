import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CopilotChat } from './CopilotChat'

vi.mock('next/dynamic', () => ({ default: () => () => <div>Analytics panel</div> }))

const DATE = '2026-10-31'
const encoder = new TextEncoder()
const sse = (...events: object[]) => events.map(e => `data: ${JSON.stringify(e)}\n\n`).join('')
const answer = (text: string, ...extra: object[]) => sse({ type: 'text', content: text }, ...extra, { type: 'done' })

type Reply = () => Promise<Response> | Response
const stream = (wire: string): Reply => () => new Response(wire, { status: 200 })
const hang: Reply = () => new Promise(() => {})

/** Replies to copilot requests in order; the published brief is answered separately. */
function mockApi(replies: Reply[] = [], brief: object | null = { narrative: 'Published brief.' }) {
  const copilot: { url: string; body: Record<string, unknown>; signal: AbortSignal }[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation((input, init) => {
    const url = String(input)
    if (url.includes('/copilot/')) {
      const signal = init?.signal as AbortSignal
      copilot.push({ url, body: JSON.parse(init?.body as string), signal })
      const reply = replies.shift() ?? stream(answer('Fine.'))
      return new Promise((resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
        Promise.resolve(reply()).then(resolve, reject)
      })
    }
    return Promise.resolve(brief ? new Response(JSON.stringify(brief), { status: 200 }) : new Response('{}', { status: 404 }))
  })
  return copilot
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>
}

const box = () => screen.getByLabelText('Message the assistant') as HTMLTextAreaElement
const type = (text: string) => fireEvent.change(box(), { target: { value: text } })
const pressEnter = (opts = {}) => fireEvent.keyDown(box(), { key: 'Enter', ...opts })
const ask = (text: string) => { type(text); pressEnter() }

beforeEach(() => {
  localStorage.clear()
  Element.prototype.scrollTo = vi.fn()
})
afterEach(cleanup)

describe('Tracker chat', () => {
  const tracker = (props = {}) => render(wrap(<CopilotChat selectedDate={DATE} activeTab="chat" {...props} />))

  it('opens with the published brief and runs no model on load', async () => {
    const copilot = mockApi()
    tracker()
    await screen.findByText('Published brief.')
    expect(copilot).toHaveLength(0)
  })

  it('says so when no brief was published', async () => {
    mockApi([], null)
    tracker()
    // The brief query retries once before reporting failure
    await screen.findByText(/No daily brief has been published/, {}, { timeout: 4000 })
    expect(screen.getByLabelText('Message the assistant')).toBeTruthy()
  })

  it('starts a new conversation when the date changes and drops the old answer', async () => {
    const copilot = mockApi([hang])
    const { rerender } = tracker()
    await screen.findByText('Published brief.')
    ask('First question')
    await waitFor(() => expect(copilot).toHaveLength(1))

    rerender(wrap(<CopilotChat selectedDate="2026-10-30" activeTab="chat" />))
    await waitFor(() => expect(copilot[0].signal.aborted).toBe(true))
    expect(screen.queryByText('First question')).toBeNull()
    await waitFor(() => expect(screen.getByLabelText('Send message')).toBeTruthy())
  })

  it('reads the brief for briefDate while questions use the forecast date', async () => {
    const copilot = mockApi([stream(answer('Tomorrow looks bad.'))])
    render(wrap(<CopilotChat selectedDate="2026-11-01" briefDate={DATE} activeTab="chat" />))
    await screen.findByText('Published brief.')
    expect(vi.mocked(fetch).mock.calls.some(([url]) => String(url).includes(`/briefs/${DATE}`))).toBe(true)
    ask('And tomorrow?')
    await screen.findByText('Tomorrow looks bad.')
    expect(copilot[0].body.date).toBe('2026-11-01')
  })

  it('offers every action the map can perform', async () => {
    mockApi([stream(answer('Done', { type: 'action', action: { type: 'set_horizon', horizon: 2 } }, { type: 'action', action: { type: 'filter_network', network: 'PAQI' } }))])
    tracker({ onAction: vi.fn() })
    await screen.findByText('Published brief.')
    ask('Go')
    await screen.findByRole('button', { name: 'Show +2 days' })
    expect(screen.getByRole('button', { name: 'Show PAQI' })).toBeTruthy()
  })
})

describe('sending', () => {
  const ready = async (replies: Reply[], props = {}) => {
    const copilot = mockApi(replies)
    const view = render(wrap(<CopilotChat selectedDate={DATE} activeTab="chat" {...props} />))
    await screen.findByText('Published brief.')
    return { copilot, ...view }
  }

  it('sends on Enter with the date and selection, and clears the box', async () => {
    const { copilot } = await ready([stream(answer('Lahore was worst'))])
    ask('  Worst city?  ')
    await screen.findByText('Lahore was worst')
    expect(copilot[0].body).toMatchObject({ message: 'Worst city?', date: DATE })
    expect(copilot[0].body.session_id).toMatch(/^[A-Za-z0-9_-]{8,80}$/)
    expect(box().value).toBe('')
  })

  it('adds a new line on Shift+Enter instead of sending', async () => {
    const { copilot } = await ready([])
    type('line one')
    pressEnter({ shiftKey: true })
    expect(copilot).toHaveLength(0)
  })

  it('does not send while an input method is composing', async () => {
    const { copilot } = await ready([])
    type('سلام')
    pressEnter({ isComposing: true })
    expect(copilot).toHaveLength(0)
  })

  it('ignores blank messages', async () => {
    const { copilot } = await ready([])
    ask('   ')
    expect(copilot).toHaveLength(0)
  })

  it('sends once when Enter is pressed twice quickly', async () => {
    const { copilot } = await ready([hang])
    type('Once')
    pressEnter()
    type('Twice')
    pressEnter()
    await waitFor(() => expect(copilot).toHaveLength(1))
  })

  it('keeps the box usable for drafting while an answer arrives', async () => {
    const { copilot } = await ready([hang])
    ask('First')
    await waitFor(() => expect(copilot).toHaveLength(1))
    expect(box().disabled).toBe(false)
    type('Next thought')
    pressEnter()
    expect(box().value).toBe('Next thought')
    expect(copilot).toHaveLength(1)
  })

  it('stops an answer and offers to try again', async () => {
    const { copilot } = await ready([hang, stream(answer('Second answer'))])
    ask('Question')
    fireEvent.click(await screen.findByLabelText('Stop the answer'))
    await screen.findByText('Stopped.')
    expect(copilot[0].signal.aborted).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByText('Second answer')
    expect(copilot[1].body).toEqual(copilot[0].body)
    expect(screen.queryByText('Stopped.')).toBeNull()
  })

  it('does not send a draft when Stop is pressed', async () => {
    const { copilot } = await ready([hang])
    ask('Question')
    const stop = await screen.findByLabelText('Stop the answer')
    type('A draft for later')
    fireEvent.click(stop)
    await screen.findByText('Stopped.')
    expect(copilot).toHaveLength(1)
    expect(box().value).toBe('A draft for later')
    // The Send button must be a different element, or the click can land on it mid-swap
    expect(screen.getByLabelText('Send message')).not.toBe(stop)
  })

  it('offers to try again after a failure and does not show suggestions', async () => {
    await ready([() => Promise.reject(new TypeError('Failed to fetch')), stream(answer('Recovered'))])
    ask('Question')
    await screen.findByRole('alert')
    expect(screen.queryByText('Ask next')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    await screen.findByText('Recovered')
  })

  it('keeps partial text when the answer fails halfway', async () => {
    await ready([stream(sse({ type: 'text', content: 'Half an answer' }))])
    ask('Question')
    await screen.findByText('Half an answer')
    await screen.findByText(/interrupted/)
  })

  it('locks the chat when the daily limit is reached, with no retry', async () => {
    const detail = "You have reached today's limit for the assistant; please try again tomorrow."
    const { copilot } = await ready([() => new Response(JSON.stringify({ detail }), { status: 429, headers: { 'Retry-After': '3600' } })])
    ask('Question')
    await screen.findByText(detail)
    expect(box().disabled).toBe(true)
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
    expect(screen.queryByText('Ask next')).toBeNull()
    pressEnter()
    expect(copilot).toHaveLength(1)
  })

  it('does not lock the chat for the per-minute limit', async () => {
    await ready([() => new Response(JSON.stringify({ detail: 'slow down' }), { status: 429, headers: { 'Retry-After': '60' } })])
    ask('Question')
    await screen.findByRole('alert')
    expect(box().disabled).toBe(false)
    expect(screen.getByRole('button', { name: 'Try again' })).toBeTruthy()
  })

  it('offers follow-up questions after an answer', async () => {
    await ready([stream(answer('Lahore was worst'))], { stations: [{ city: 'Lahore', pm25: 200, band: 'hazardous' }] })
    ask('Question')
    fireEvent.click(await screen.findByRole('button', { name: 'How is Lahore looking for the next 3 days?' }))
    await screen.findByText('How is Lahore looking for the next 3 days?')
  })

  it('turns the follow-ups the model wrote into buttons and removes them from the answer', async () => {
    await ready([stream(answer('Eminabad was worst.\n\nSuggested Follow-ups:\n\n- Tell me more about Eminabad.\n- What needs attention today?'))])
    ask('Question')
    await screen.findByText('Eminabad was worst.')
    expect(screen.queryByText('Suggested Follow-ups:')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Tell me more about Eminabad.' }))
    await screen.findByText('Tell me more about Eminabad.')
  })

  it('writes the answer out, holding the buttons back until it finishes', async () => {
    const words = 'Air quality was poor across Punjab because calm winds trapped smoke over the cities that day. '
    await ready([stream(answer(words.repeat(3), { type: 'action', action: { type: 'zoom_to_city', city: 'Lahore' } }))], { onAction: vi.fn() })
    ask('Question')
    await screen.findByText(/Air quality/)
    const log = screen.getByRole('log')
    expect(log.textContent?.length).toBeLessThan(words.length * 3)
    expect(screen.queryByRole('button', { name: 'Show Lahore' })).toBeNull()
    expect(screen.queryByText('Ask next')).toBeNull()
    await screen.findByRole('button', { name: 'Show Lahore' }, { timeout: 5000 })
    expect(log.textContent).toContain(words.repeat(3).trim().slice(-40))
    await screen.findByText('Ask next')
  })

  it('shows the published brief at once rather than typing it', async () => {
    mockApi([], { narrative: 'A long published brief. '.repeat(10) })
    render(wrap(<CopilotChat selectedDate={DATE} activeTab="chat" />))
    await screen.findByText('Try asking')
    expect(screen.getByRole('log').textContent).toContain('A long published brief.')
  })

  it('shows the whole answer at once for people who turn off motion', async () => {
    const original = window.matchMedia
    window.matchMedia = vi.fn().mockReturnValue({ matches: true }) as unknown as typeof window.matchMedia
    try {
      const text = 'Calm winds trapped smoke. '.repeat(20)
      await ready([stream(answer(text))])
      ask('Question')
      await screen.findByText('Ask next')
      expect(screen.getByRole('log').textContent).toContain(text.trim())
    } finally {
      window.matchMedia = original
    }
  })

  it('keeps following the answer unless the reader scrolls up', async () => {
    await ready([])
    const log = screen.getByRole('log')
    const scrollTo = (scrollTop: number, scrollHeight: number) => {
      Object.defineProperty(log, 'scrollHeight', { value: scrollHeight, configurable: true })
      Object.defineProperty(log, 'clientHeight', { value: 400, configurable: true })
      log.scrollTop = scrollTop
      fireEvent.scroll(log)
    }
    scrollTo(600, 1000)
    // Content grew underneath before the follow-scroll landed: not the reader's doing
    scrollTo(600, 1300)
    expect(screen.queryByLabelText('Jump to latest message')).toBeNull()
    scrollTo(300, 1300)
    expect(screen.getByLabelText('Jump to latest message')).toBeTruthy()
    scrollTo(880, 1300)
    expect(screen.queryByLabelText('Jump to latest message')).toBeNull()
  })

  it('runs an action as it arrives, and again when its button is pressed', async () => {
    const onAction = vi.fn()
    const zoom = { type: 'zoom_to_city', city: 'Lahore' }
    await ready([stream(answer('See map', { type: 'action', action: zoom }))], { onAction })
    ask('Question')
    fireEvent.click(await screen.findByRole('button', { name: 'Show Lahore' }))
    expect(onAction.mock.calls).toEqual([[zoom, false], [zoom, true]])
  })

  it('ignores an unknown action from the model', async () => {
    const onAction = vi.fn()
    await ready([stream(answer('Hello', { type: 'action', action: { type: 'wipe' } }))], { onAction })
    ask('Question')
    await screen.findByText('Hello')
    expect(onAction).not.toHaveBeenCalled()
  })

  it('cancels the request when the chat is closed mid-answer', async () => {
    const { copilot, unmount } = await ready([hang])
    ask('Question')
    await waitFor(() => expect(copilot).toHaveLength(1))
    unmount()
    expect(copilot[0].signal.aborted).toBe(true)
  })

  it('tells the page when streaming starts and stops', async () => {
    const onStreamingChange = vi.fn()
    await ready([stream(answer('Done'))], { onStreamingChange })
    ask('Question')
    await screen.findByText('Done')
    await waitFor(() => expect(onStreamingChange.mock.calls).toEqual([[true], [false]]))
  })

  it('copes with the clipboard being blocked', async () => {
    Object.assign(navigator, { clipboard: { writeText: () => Promise.reject(new Error('denied')) } })
    await ready([stream(answer('Copy me'))])
    ask('Question')
    await screen.findByText('Copy me')
    const buttons = screen.getAllByRole('button', { name: 'Copy answer' })
    await act(async () => { fireEvent.click(buttons[buttons.length - 1]) })
    expect(screen.queryByText('Copied')).toBeNull()
  })

  it('renders a split response in full', async () => {
    const wire = encoder.encode(answer('Complete'))
    await ready([() => new Response(new ReadableStream({
      start(c) { c.enqueue(wire.slice(0, 10)); c.enqueue(wire.slice(10)); c.close() },
    }))])
    ask('Question')
    await screen.findByText('Complete')
  })
})
