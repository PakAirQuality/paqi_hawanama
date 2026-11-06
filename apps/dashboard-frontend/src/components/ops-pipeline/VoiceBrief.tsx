'use client'

import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, m } from 'motion/react'
import { Loader2, Volume2 } from 'lucide-react'
import { briefKey, isBriefResponse, requestBody, type VoiceAvailability, type VoiceLang, type VoiceTarget } from '@/lib/voiceBrief'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? ''

/** A zero-length WAV: played inside the tap so iPhone Safari lets the real brief play once it arrives. */
const SILENT_WAV = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAESsAACJWAAACABAAZGF0YQAAAAA='
const LANG_KEY = 'hawanama-voice-lang'

type Status = 'idle' | 'locating' | 'loading' | 'playing'

/** A tap waiting on the location or the readings gives up after this long. */
const WAIT_LIMIT_MS = 30_000

/** Synthesis takes up to ~15 s; past this the request is given up. */
const FETCH_TIMEOUT_MS = 45_000
/** Recordings kept in the page (each about 1 MB). */
const MAX_RECORDINGS = 6

interface Recording { url: string; text: string }

/** What the button says when something goes wrong, in the brief's language. */
const NOTES = {
  down: { en: 'The voice brief is unavailable right now. Try again shortly.', ur: 'آواز ابھی دستیاب نہیں۔ کچھ دیر بعد کوشش کریں۔' },
  busy: { en: 'Too many requests. Try again in a minute.', ur: 'بہت زیادہ درخواستیں۔ ایک منٹ بعد کوشش کریں۔' },
  tapAgain: { en: 'Your brief is ready. Tap Listen to play it.', ur: 'آپ کی بریفنگ تیار ہے۔ سننے کے لیے دوبارہ دبائیں۔' },
  noAudio: { en: 'This browser cannot play audio.', ur: 'یہ براؤزر آواز نہیں چلا سکتا۔' },
  noMonitor: { en: 'There is no air quality monitor within 50 km of you.', ur: 'آپ سے 50 کلومیٹر کے اندر کوئی مانیٹر نہیں۔' },
  outside: { en: 'The voice brief covers locations in Pakistan.', ur: 'آواز میں بریفنگ صرف پاکستان کے مقامات کے لیے ہے۔' },
  noLocation: { en: 'Share your location to hear the air quality near you.', ur: 'اپنے قریب ہوا کا معیار سننے کے لیے اپنا مقام شیئر کریں۔' },
} as const

function storedLang(): VoiceLang {
  try {
    const v = localStorage.getItem(LANG_KEY)
    if (v === 'en' || v === 'ur') return v
  } catch { /* storage unavailable */ }
  return typeof navigator !== 'undefined' && navigator.language?.toLowerCase().startsWith('ur') ? 'ur' : 'en'
}

/**
 * "Listen" (in the header): reads the air quality at the visitor's nearest monitor aloud, in English or Urdu,
 * with no transcript on screen. Browsers allow sound only after a tap, so the brief starts from this button. Without a location yet, the tap asks for one
 * and the brief follows as soon as the nearest monitor is known.
 */
export function VoiceBrief({ target, availability, locationFailed, onRequestLocation, className = '' }: {
  /** The nearest monitor's live reading, once the visitor's location is known */
  target: VoiceTarget | null
  /** Whether a brief can be made yet (see voiceTarget) */
  availability: VoiceAvailability
  /** Bumped when a location request fails, so a waiting brief gives up */
  locationFailed: number
  onRequestLocation: () => void
  className?: string
}) {
  const [lang, setLang] = useState<VoiceLang>('en')
  const [status, setStatus] = useState<Status>('idle')
  const [note, setNote] = useState<string | null>(null)
  const audio = useRef<HTMLAudioElement | null>(null)
  // One recording per reading and language, shared by the background prefetch and the tap
  const recordings = useRef(new Map<string, Promise<Recording | null>>())
  // Bumped by every tap and stop: a recording that arrives for an older tap is not played
  const turn = useRef(0)
  // Why the last request failed, for the note: too many requests, or anything else
  const lastFailure = useRef<'busy' | 'down'>('down')

  useEffect(() => { setLang(storedLang()) }, [])
  useEffect(() => () => {
    turn.current++
    audio.current?.pause()
    for (const r of recordings.current.values()) void r.then(rec => { if (rec) URL.revokeObjectURL(rec.url) })
  }, [])
  useEffect(() => {
    if (!note) return
    const t = setTimeout(() => setNote(null), 5000)
    return () => clearTimeout(t)
  }, [note])

  /** The recording for this reading, fetched once (a failed fetch is forgotten, so a later tap retries). */
  const recording = (t: VoiceTarget, l: VoiceLang): Promise<Recording | null> => {
    const key = `${l}|${briefKey(t)}`
    const known = recordings.current.get(key)
    if (known) return known
    const p = (async (): Promise<Recording | null> => {
      // A request that hangs gives up, so the button never waits forever
      const ac = new AbortController()
      const timer = setTimeout(() => ac.abort(), FETCH_TIMEOUT_MS)
      try {
        // The trailing slash matters: the site's hosting answers /brief with a 301 to /brief/, and a browser
        // follows a 301 on a POST as a GET (the API answers both forms)
        const res = await fetch(`${API_BASE}/api/v1/voice/brief/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody(t, l)),
          signal: ac.signal,
        })
        if (!res.ok) { lastFailure.current = res.status === 429 ? 'busy' : 'down'; return forget(key) }
        const body: unknown = await res.json()
        if (!isBriefResponse(body)) { lastFailure.current = 'down'; return forget(key) }
        const bytes = Uint8Array.from(atob(body.audio), c => c.charCodeAt(0))
        if (!bytes.length) { lastFailure.current = 'down'; return forget(key) }
        return { url: URL.createObjectURL(new Blob([bytes], { type: body.mime || 'audio/wav' })), text: body.text }
      } catch {
        lastFailure.current = 'down'
        return forget(key)
      } finally {
        clearTimeout(timer)
      }
    })()
    recordings.current.set(key, p)
    // Keep only the newest few recordings; older ones are released
    while (recordings.current.size > MAX_RECORDINGS) {
      const [oldKey, old] = recordings.current.entries().next().value as [string, Promise<Recording | null>]
      recordings.current.delete(oldKey)
      // (never the one playing)
      void old.then(rec => { if (rec && audio.current?.src !== rec.url) URL.revokeObjectURL(rec.url) })
    }
    return p
  }
  const forget = (key: string): null => { recordings.current.delete(key); return null }

  // Make the brief in the background as soon as the nearest monitor is known, so a tap usually plays at once
  // (the synthesis takes several seconds). The server caches it, so visitors near the same monitor share it.
  const targetKey = target ? briefKey(target) : null
  useEffect(() => {
    if (!target) return
    const t = setTimeout(() => { void recording(target, lang) }, 600)
    return () => clearTimeout(t)
  }, [targetKey, lang]) // eslint-disable-line react-hooks/exhaustive-deps

  /** The page's one audio element (null where the browser cannot play audio). */
  const player = (): HTMLAudioElement | null => {
    if (!audio.current) {
      let a: HTMLAudioElement
      try { a = new Audio() } catch { return null }
      // The silent unlock clip ends at once; only the brief's own end resets the button
      const done = () => { if (a.src !== SILENT_WAV) setStatus('idle') }
      a.onended = done
      a.onerror = done
      audio.current = a
    }
    return audio.current
  }

  const stop = () => {
    turn.current++
    audio.current?.pause()
    setStatus('idle')
  }

  const speak = async (t: VoiceTarget, l: VoiceLang) => {
    const mine = ++turn.current
    const a = player()
    if (!a) { setStatus('idle'); setNote(NOTES.noAudio[l]); return }
    setStatus('loading')
    const rec = await recording(t, l)
    if (mine !== turn.current) return // stopped, or tapped again, while it was being made
    if (!rec) {
      setStatus('idle')
      setNote(lastFailure.current === 'busy' ? NOTES.busy[l] : NOTES.down[l])
      return
    }
    try {
      a.src = rec.url
      setStatus('playing')
      await a.play()
    } catch {
      // Usually the browser refusing sound that did not start from a tap (a long wait on iPhone):
      // the recording is ready now, so another tap plays it at once
      if (mine === turn.current) { setStatus('idle'); setNote(NOTES.tapAgain[l]) }
    }
  }

  // A tap waiting on the location or the readings goes on as soon as either answer is known
  useEffect(() => {
    if (status !== 'locating') return
    if (availability === 'ready' && target) { void speak(target, lang); return }
    if (availability === 'no-monitor') { setStatus('idle'); setNote(NOTES.noMonitor[lang]); return }
    if (availability === 'no-data') { setStatus('idle'); setNote(NOTES.down[lang]); return }
    if (availability === 'outside') { setStatus('idle'); setNote(NOTES.outside[lang]) }
  }, [status, target, availability]) // eslint-disable-line react-hooks/exhaustive-deps
  // ...and never waits forever (a location prompt left unanswered, a fly-in that never ends)
  useEffect(() => {
    if (status !== 'locating') return
    const t = setTimeout(() => { setStatus('idle'); setNote(NOTES.down[lang]) }, WAIT_LIMIT_MS)
    return () => clearTimeout(t)
  }, [status]) // eslint-disable-line react-hooks/exhaustive-deps
  // The location request ended without a location: say why here, by the button (outside Pakistan has its own note)
  useEffect(() => {
    if (!locationFailed || status !== 'locating') return
    setStatus('idle')
    setNote(availability === 'outside' ? NOTES.outside[lang] : NOTES.noLocation[lang])
  }, [locationFailed]) // eslint-disable-line react-hooks/exhaustive-deps

  const onTap = () => {
    if (status === 'playing' || status === 'loading' || status === 'locating') { stop(); return }
    // Unlock audio inside the tap (iPhone Safari), before any network wait
    const a = player()
    if (!a) { setNote(NOTES.noAudio[lang]); return }
    try {
      a.src = SILENT_WAV
      void a.play().catch(() => { /* nothing to play yet */ })
    } catch { /* the unlock is a nicety; the brief can still play */ }
    if (availability === 'ready' && target) { void speak(target, lang); return }
    if (availability === 'no-monitor') { setNote(NOTES.noMonitor[lang]); return }
    if (availability === 'no-data') { setNote(NOTES.down[lang]); return }
    // Already known to be outside Pakistan this visit: say so, without asking for the location again
    if (availability === 'outside') { setNote(NOTES.outside[lang]); return }
    setStatus('locating')
    // Ask for the location only when it is not known; otherwise just wait for the readings
    if (availability === 'no-location') onRequestLocation()
  }

  const chooseLang = (l: VoiceLang) => {
    if (l === lang) return
    setLang(l)
    try { localStorage.setItem(LANG_KEY, l) } catch { /* storage unavailable */ }
    // Switching while it speaks restarts the brief in the other language
    if ((status === 'playing' || status === 'loading') && availability === 'ready' && target) {
      audio.current?.pause()
      void speak(target, l)
    }
  }

  const busy = status === 'loading' || status === 'locating'
  const label = status === 'playing' ? 'Stop' : status === 'loading' ? 'Preparing…' : status === 'locating' ? 'Finding you…' : 'Listen'

  return (
    <div className={`relative flex items-center gap-0.5 rounded-full bg-slate-900/[0.045] p-0.5 ${className}`}>
      <button
        onClick={onTap}
        aria-label={status === 'playing' ? 'Stop the air quality brief' : 'Listen to the air quality near you'}
        title={status === 'playing' ? 'Stop' : 'Listen to the air quality near you'}
        className="flex h-8 items-center gap-1.5 rounded-full px-2 text-[13px] font-medium text-slate-800 transition-[background-color,transform] duration-150 hover:bg-white hover:shadow-sm active:scale-95 sm:pl-2.5 sm:pr-3"
      >
        <span className="flex h-4 w-4 items-center justify-center">
          {busy ? <Loader2 className="h-4 w-4 animate-spin text-slate-500" />
            : status === 'playing' ? <SoundBars />
            : <Volume2 className="h-4 w-4" />}
        </span>
        <span className="hidden sm:inline">{label}</span>
      </button>
      <div className="flex" role="radiogroup" aria-label="Brief language">
        {(['en', 'ur'] as const).map(l => (
          <button
            key={l}
            role="radio"
            aria-checked={lang === l}
            onClick={() => chooseLang(l)}
            lang={l}
            className={`h-7 rounded-full px-2 text-[11px] font-semibold transition-colors duration-150 ${lang === l ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
          >
            {l === 'en' ? 'EN' : 'اردو'}
          </button>
        ))}
      </div>

      {/* Only problems are shown (no transcript): a short note under the control */}
      <AnimatePresence>
        {note && (
          <m.div
            key="note"
            initial={{ opacity: 0, y: -4 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.2 }}
            role="status"
            dir={lang === 'ur' ? 'rtl' : 'ltr'}
            lang={lang}
            className="absolute right-0 top-full z-50 mt-2 w-max max-w-[260px] rounded-xl bg-slate-900 px-3 py-2 text-xs leading-snug text-white shadow-lg"
          >
            {note}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}

/** Three bars that rise and fall while the brief speaks. */
function SoundBars() {
  return (
    <span className="flex h-3.5 items-end gap-[2px]" aria-hidden>
      {[0, 0.2, 0.4].map(d => (
        <m.span
          key={d}
          className="w-[3px] rounded-full bg-slate-900"
          animate={{ height: ['30%', '100%', '45%', '80%', '30%'] }}
          transition={{ duration: 1, repeat: Infinity, delay: d, ease: 'easeInOut' }}
        />
      ))}
    </span>
  )
}
