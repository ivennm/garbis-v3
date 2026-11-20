/** App state (zustand). The controller writes it; components read it. */
import { create } from 'zustand'
import type { Settings } from '../../../shared/types'
import type { FaceState, HeardAction, Mode, ModeStatus } from '../net/protocol'
import type { ConnStatus } from '../net/socket'

export type EntryKind = 'heard' | 'said' | 'timing' | 'system' | 'error'

export interface Entry {
  id: number
  kind: EntryKind
  text: string
  at: number
  source?: string // heard: mic | desktop
  action?: HeardAction // heard: what Garbis did with it
  turnId?: number // said / timing
}

export type Panel = 'none' | 'transcript' | 'settings'

export interface GarbisState {
  conn: ConnStatus
  connDetail: string | null
  active: boolean
  activeDevice: string | null
  face: FaceState
  source: string | null
  mode: Mode
  modeStatus: ModeStatus
  model: string
  muted: boolean
  micError: string | null
  micLevel: number
  desktopLive: boolean // desktop audio is being captured
  desktopError: string | null
  desktopLevel: number
  screenLive: boolean // screenshots are being sent (screen vision on and working)
  screenError: string | null
  settings: Settings | null
  panel: Panel
  transcript: Entry[]
}

export const MAX_TRANSCRIPT = 200

export const initialState: GarbisState = {
  conn: 'connecting',
  connDetail: null,
  active: false,
  activeDevice: null,
  face: 'idle',
  source: null,
  mode: 'low',
  modeStatus: 'ready',
  model: '',
  muted: false,
  micError: null,
  micLevel: 0,
  desktopLive: false,
  desktopError: null,
  desktopLevel: 0,
  screenLive: false,
  screenError: null,
  settings: null,
  panel: 'none',
  transcript: []
}

export const useGarbis = create<GarbisState>()(() => ({ ...initialState }))

let nextId = 1

function push(entry: Omit<Entry, 'id' | 'at'>): void {
  useGarbis.setState((s) => ({
    transcript: [...s.transcript, { ...entry, id: nextId++, at: Date.now() }].slice(-MAX_TRANSCRIPT)
  }))
}

export function addEntry(kind: EntryKind, text: string, extra: Pick<Entry, 'source' | 'action' | 'turnId'> = {}): void {
  push({ kind, text, ...extra })
}

/**
 * Garbis's sentences arrive one by one; one reply is one transcript line. The reply's timing
 * line arrives after its first sentence starts, so look past it.
 */
export function addSaid(turnId: number, text: string): void {
  useGarbis.setState((s) => {
    const t = s.transcript
    let i = t.length - 1
    while (i >= 0 && t[i].kind === 'timing' && t[i].turnId === turnId) i--
    const line = t[i]
    if (line && line.kind === 'said' && line.turnId === turnId) {
      const merged = { ...line, text: `${line.text} ${text}` }
      return { transcript: [...t.slice(0, i), merged, ...t.slice(i + 1)] }
    }
    return {
      transcript: [...s.transcript, { id: nextId++, kind: 'said' as const, text, turnId, at: Date.now() }].slice(
        -MAX_TRANSCRIPT
      )
    }
  })
}

export function clearTranscript(): void {
  useGarbis.setState({ transcript: [] })
}

// ---- what the face shows ----

export type FaceView = FaceState | 'offline' | 'inactive' | 'switching'

const LABELS: Record<FaceState, string> = {
  idle: 'Idle',
  listen: 'Listening',
  think: 'Thinking...',
  speak: 'Speaking'
}

/** The face and status line for the current state (ARCHITECTURE.md §4.5). */
export function describe(
  s: Pick<
    GarbisState,
    'conn' | 'connDetail' | 'active' | 'activeDevice' | 'face' | 'source' | 'modeStatus' | 'muted' | 'micError'
  >
): { view: FaceView; status: string } {
  if (s.conn === 'refused') return { view: 'offline', status: s.connDetail ?? 'The server refused the connection' }
  if (s.conn === 'connecting') return { view: 'offline', status: 'Connecting…' }
  if (s.conn === 'offline') return { view: 'offline', status: "Can't reach the server, retrying…" }
  if (!s.active) return { view: 'inactive', status: `Active on ${s.activeDevice ?? 'another device'}` }
  if (s.modeStatus === 'loading' && s.face !== 'speak') return { view: 'switching', status: 'Switching brains…' }
  if (s.micError) return { view: s.face, status: s.micError }
  let status = LABELS[s.face]
  if (s.face === 'listen' && s.source) status += ` (${s.source})`
  if (s.face === 'idle' && s.muted) status += ' (mic muted)'
  return { view: s.face, status }
}
