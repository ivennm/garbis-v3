import { describe, expect, it } from 'vitest'
import { ClipPlayer } from './player'
import type { AudioOut, PlayHandle } from './player'

/** A fake speaker: clips "play" until finish() or stop() is called. */
class FakeOut implements AudioOut {
  playing: { name: string; end: () => void }[] = []
  failDecode = new Set<string>()

  decode(mp3: ArrayBuffer): Promise<AudioBuffer> {
    const name = new TextDecoder().decode(mp3)
    if (this.failDecode.has(name)) return Promise.reject(new Error('bad mp3'))
    return Promise.resolve({ name } as unknown as AudioBuffer)
  }

  play(buffer: AudioBuffer, onEnded: () => void): PlayHandle {
    const name = (buffer as unknown as { name: string }).name
    let done = false
    const end = () => {
      if (done) return
      done = true
      this.playing = this.playing.filter((p) => p.name !== name)
      queueMicrotask(onEnded) // Web Audio fires onended asynchronously
    }
    this.playing.push({ name, end })
    return { stop: end }
  }

  /** The current clip reaches its end naturally. */
  finish(): void {
    this.playing[0]?.end()
  }
}

const mp3 = (name: string) => new TextEncoder().encode(name).buffer as ArrayBuffer
const tick = () => new Promise((r) => setTimeout(r, 0))

function setup() {
  const out = new FakeOut()
  const events: string[] = []
  const player = new ClipPlayer(out, {
    started: (t, s) => events.push(`start ${t}/${s}`),
    ended: (t, s, interrupted) => events.push(`end ${t}/${s}${interrupted ? ' (cut)' : ''}`)
  })
  return { out, events, player }
}

describe('ClipPlayer', () => {
  it('plays clips one after another in arrival order', async () => {
    const { out, events, player } = setup()
    player.add(1, 0, mp3('a'))
    player.add(1, 1, mp3('b'))
    await tick()
    expect(out.playing.map((p) => p.name)).toEqual(['a'])
    expect(player.playing).toBe(true)

    out.finish()
    await tick()
    expect(out.playing.map((p) => p.name)).toEqual(['b'])
    out.finish()
    await tick()

    expect(events).toEqual(['start 1/0', 'end 1/0', 'start 1/1', 'end 1/1'])
    expect(player.playing).toBe(false)
    expect(player.lastEnd).toBeGreaterThan(0)
  })

  it('stop_audio cuts the current clip and drops the rest of that turn', async () => {
    const { out, events, player } = setup()
    player.add(1, 0, mp3('a'))
    player.add(1, 1, mp3('b'))
    await tick()
    player.stop(1)
    await tick()
    player.add(1, 2, mp3('late')) // arrives after the stop: ignored
    await tick()

    expect(events).toEqual(['start 1/0', 'end 1/0 (cut)'])
    expect(out.playing).toEqual([])
  })

  it('keeps playing the next turn after a stopped one', async () => {
    const { out, events, player } = setup()
    player.add(1, 0, mp3('a'))
    await tick()
    player.stop(1)
    player.add(2, 0, mp3('next'))
    await tick()
    await tick()
    expect(out.playing.map((p) => p.name)).toEqual(['next'])
    out.finish()
    await tick()
    expect(events).toEqual(['start 1/0', 'end 1/0 (cut)', 'start 2/0', 'end 2/0'])
  })

  it('stopAll silences everything', async () => {
    const { out, events, player } = setup()
    player.add(1, 0, mp3('a'))
    player.add(2, 0, mp3('b'))
    await tick()
    player.stopAll()
    await tick()
    await tick()
    expect(events).toEqual(['start 1/0', 'end 1/0 (cut)'])
    expect(out.playing).toEqual([])
  })

  it('reports a clip that cannot be decoded as ended, and carries on', async () => {
    const { out, events, player } = setup()
    out.failDecode.add('bad')
    player.add(1, 0, mp3('bad'))
    player.add(1, 1, mp3('good'))
    await tick()
    await tick()
    expect(events).toEqual(['end 1/0 (cut)', 'start 1/1'])
  })
})
