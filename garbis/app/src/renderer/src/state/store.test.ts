import { describe as group, expect, it } from 'vitest'
import { DEFAULT_SETTINGS, sanitizeSettings } from '../../../shared/settings'
import { describe, initialState } from './store'

const online = { ...initialState, conn: 'online' as const, active: true }

group('what the face shows', () => {
  it('shows offline faces until connected', () => {
    expect(describe({ ...initialState, conn: 'connecting' })).toEqual({ view: 'offline', status: 'Connecting…' })
    expect(describe({ ...initialState, conn: 'offline' }).status).toBe("Can't reach the server, retrying…")
    expect(describe({ ...initialState, conn: 'refused', connDetail: 'wrong token' })).toEqual({
      view: 'offline',
      status: 'wrong token'
    })
  })

  it('shows the inactive face when another device has Garbis', () => {
    expect(describe({ ...online, active: false, activeDevice: 'ivean-pc' })).toEqual({
      view: 'inactive',
      status: 'Active on ivean-pc'
    })
  })

  it('follows the server state like v2', () => {
    expect(describe(online)).toEqual({ view: 'idle', status: 'Idle' })
    expect(describe({ ...online, face: 'listen', source: 'mic' }).status).toBe('Listening (mic)')
    expect(describe({ ...online, face: 'think' }).status).toBe('Thinking...')
    expect(describe({ ...online, face: 'speak', source: 'mic' }).status).toBe('Speaking')
    expect(describe({ ...online, muted: true }).status).toBe('Idle (mic muted)')
  })

  it('shows switching brains while a mode loads, except while he says so', () => {
    expect(describe({ ...online, modeStatus: 'loading' }).view).toBe('switching')
    expect(describe({ ...online, modeStatus: 'loading', face: 'speak' }).view).toBe('speak')
  })

  it('puts mic problems in the status line', () => {
    expect(describe({ ...online, micError: 'Mic blocked' })).toEqual({ view: 'idle', status: 'Mic blocked' })
  })
})

group('settings', () => {
  it('fills in defaults and drops bad values', () => {
    const s = sanitizeSettings({ token: 'abc', volume: 7, echoCancellation: 'yes', unknown: 1, serverUrl: '  ' })
    expect(s.token).toBe('abc')
    expect(s.volume).toBe(1)
    expect(s.echoCancellation).toBe(DEFAULT_SETTINGS.echoCancellation) // "yes" is not a boolean
    expect(s.serverUrl).toBe(DEFAULT_SETTINGS.serverUrl)
    expect(s).not.toHaveProperty('unknown')
  })

  it('applies a patch on top of current settings', () => {
    const current = sanitizeSettings({ token: 'abc', volume: 0.5 })
    const next = sanitizeSettings({ volume: 0.2 }, current)
    expect(next).toMatchObject({ token: 'abc', volume: 0.2 })
  })

  it('survives garbage', () => {
    expect(sanitizeSettings(null)).toEqual(DEFAULT_SETTINGS)
    expect(sanitizeSettings('nope')).toEqual(DEFAULT_SETTINGS)
  })
})

group('transcript', () => {
  it("groups one reply's sentences into one line, and keeps turns apart", async () => {
    const { addEntry, addSaid, clearTranscript, useGarbis } = await import('./store')
    clearTranscript()
    addEntry('heard', 'hey garbis', { source: 'mic', action: 'reply' })
    addSaid(1, 'Beep boop,')
    addSaid(1, "it's 4!")
    addEntry('timing', '1.44 s', { turnId: 1 })
    addSaid(2, 'Next reply.')
    const t = useGarbis.getState().transcript
    expect(t.map((e) => [e.kind, e.text])).toEqual([
      ['heard', 'hey garbis'],
      ['said', "Beep boop, it's 4!"],
      ['timing', '1.44 s'],
      ['said', 'Next reply.']
    ])
    expect(t[0]).toMatchObject({ source: 'mic', action: 'reply' })
  })

  it('keeps a reply on one line when its timing arrives mid-reply', async () => {
    const { addEntry, addSaid, clearTranscript, useGarbis } = await import('./store')
    clearTranscript()
    addSaid(7, 'First sentence.')
    addEntry('timing', '2.35 s', { turnId: 7 })
    addSaid(7, 'Second sentence.')
    expect(useGarbis.getState().transcript.map((e) => [e.kind, e.text])).toEqual([
      ['said', 'First sentence. Second sentence.'],
      ['timing', '2.35 s']
    ])
  })

  it('keeps only the last MAX_TRANSCRIPT entries', async () => {
    const { addEntry, clearTranscript, useGarbis, MAX_TRANSCRIPT } = await import('./store')
    clearTranscript()
    for (let i = 0; i < MAX_TRANSCRIPT + 5; i++) addEntry('system', `line ${i}`)
    const t = useGarbis.getState().transcript
    expect(t).toHaveLength(MAX_TRANSCRIPT)
    expect(t[0].text).toBe('line 5')
  })
})
