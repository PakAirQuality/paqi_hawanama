// One copilot request from start to finish. Every way it can end comes back as an outcome, so the
// chat never has to work out from an exception what to tell the user.

import type { CopilotAction } from '@/components/analyst-desk/types'
import { actionKey, extractActions, parseAction } from './actions'
import { createSseParser } from './sse'

export type StreamOutcome =
  | { status: 'ok' }
  | { status: 'stopped' }
  | { status: 'limit'; message: string }        // today's allowance is used up: retrying cannot help
  | { status: 'busy'; message: string }         // short-term rate limit: fine again in a moment
  | { status: 'unavailable'; message: string }  // the service is down
  | { status: 'error'; message: string }        // this reply failed

const DEFAULT_MESSAGES = {
  limit: 'The assistant has reached its usage limit for today. Please try again tomorrow.',
  busy: 'Too many questions in a short time. Please wait a moment and try again.',
  unavailable: 'The assistant is temporarily unavailable. Please try again shortly.',
  failed: 'Could not reach the assistant. Please check your connection and try again.',
  interrupted: 'The answer was interrupted. Please try again.',
  empty: 'The assistant did not return an answer. Please try again.',
}

// The API allows up to 8 tool round-trips before the first word, so silence can be long.
export const STALL_MS = 90_000
// The per-minute limit clears quickly; the daily limit sends Retry-After: 3600.
const SHORT_WAIT_SECONDS = 120

interface StreamOptions {
  url: string
  body: object
  signal: AbortSignal
  onText: (text: string) => void
  onAction: (action: CopilotAction) => void
  stallMs?: number
}

async function readDetail(res: Response): Promise<string | null> {
  try {
    const data = await res.json()
    return typeof data?.detail === 'string' ? data.detail : null
  } catch {
    return null
  }
}

async function outcomeForStatus(res: Response): Promise<StreamOutcome> {
  const detail = await readDetail(res)
  if (res.status === 429) {
    const wait = Number(res.headers.get('Retry-After'))
    const daily = /tomorrow|today|daily/i.test(detail ?? '') || wait >= SHORT_WAIT_SECONDS
    return daily
      ? { status: 'limit', message: detail ?? DEFAULT_MESSAGES.limit }
      : { status: 'busy', message: DEFAULT_MESSAGES.busy }
  }
  if (res.status === 503) return { status: 'unavailable', message: detail ?? DEFAULT_MESSAGES.unavailable }
  return { status: 'error', message: DEFAULT_MESSAGES.failed }
}

export async function streamCopilot({ url, body, signal, onText, onAction, stallMs = STALL_MS }: StreamOptions): Promise<StreamOutcome> {
  // Our own controller, so the stall timer can end the request as well as the Stop button
  const controller = new AbortController()
  const stopForUser = () => controller.abort()
  if (signal.aborted) return { status: 'stopped' }
  signal.addEventListener('abort', stopForUser)

  let stalled = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const watch = () => {
    clearTimeout(timer)
    timer = setTimeout(() => { stalled = true; controller.abort() }, stallMs)
  }

  let raw = ''
  const seen = new Set<string>()
  const emit = (action: CopilotAction | null) => {
    if (!action || seen.has(actionKey(action))) return
    seen.add(actionKey(action))
    onAction(action)
  }

  try {
    watch()
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })
    if (!res.ok) return await outcomeForStatus(res)
    if (!res.body) return { status: 'error', message: DEFAULT_MESSAGES.failed }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    const parser = createSseParser()
    let finished = false
    let failed: string | null = null

    const handle = (events: ReturnType<typeof parser.push>) => {
      for (const event of events) {
        if (event.type === 'text') {
          raw += event.content
          const { clean, actions } = extractActions(raw)
          actions.forEach(emit)
          onText(clean)
        } else if (event.type === 'action') {
          emit(parseAction(event.action))
        } else if (event.type === 'error') {
          // The API's text here is generic by design; show our own wording with a way to retry
          failed = DEFAULT_MESSAGES.interrupted
        } else {
          finished = true
        }
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      watch()
      if (done) break
      handle(parser.push(decoder.decode(value, { stream: true })))
    }
    handle(parser.push(decoder.decode()))
    handle(parser.flush())

    if (failed) return { status: 'error', message: failed }
    if (!finished) return { status: 'error', message: DEFAULT_MESSAGES.interrupted }
    if (!extractActions(raw).clean.trim()) return { status: 'error', message: DEFAULT_MESSAGES.empty }
    return { status: 'ok' }
  } catch {
    if (stalled) return { status: 'error', message: DEFAULT_MESSAGES.interrupted }
    if (signal.aborted) return { status: 'stopped' }
    return { status: 'error', message: raw ? DEFAULT_MESSAGES.interrupted : DEFAULT_MESSAGES.failed }
  } finally {
    clearTimeout(timer)
    signal.removeEventListener('abort', stopForUser)
  }
}
