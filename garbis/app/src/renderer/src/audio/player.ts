/**
 * Plays Garbis's clips in order and reports back (ARCHITECTURE.md §4.4).
 *
 * The server sends clips as soon as they're synthesized; this queues them, plays them one after
 * another, and reports clip_started / clip_ended. stop_audio cuts the current clip at once and
 * drops the rest of that turn.
 */

export interface PlayHandle {
  stop(): void
}

/** The sound output, so the queue logic can be tested without Web Audio. */
export interface AudioOut {
  decode(mp3: ArrayBuffer): Promise<AudioBuffer>
  play(buffer: AudioBuffer, onEnded: () => void): PlayHandle
}

export interface PlayerEvents {
  started(turnId: number, seq: number): void
  ended(turnId: number, seq: number, interrupted: boolean): void
}

interface Item {
  turnId: number
  seq: number
  buffer: Promise<AudioBuffer>
}

interface Current {
  item: Item
  handle: PlayHandle | null
  stopped: boolean
}

const MAX_DROPPED = 100

export class ClipPlayer {
  private queue: Item[] = []
  private current: Current | null = null
  private dropped = new Set<number>()
  private pumping = false
  /** performance.now() when the last clip finished; desktop-audio echo gating uses it (M3). */
  lastEnd = 0

  constructor(
    private readonly out: AudioOut,
    private readonly events: PlayerEvents
  ) {}

  get playing(): boolean {
    return this.current !== null
  }

  add(turnId: number, seq: number, mp3: ArrayBuffer): void {
    if (this.dropped.has(turnId)) return
    const buffer = this.out.decode(mp3)
    buffer.catch(() => undefined) // reported when its turn comes
    this.queue.push({ turnId, seq, buffer })
    void this.pump()
  }

  /** stop_audio: cut this turn now and drop its queued clips. */
  stop(turnId: number): void {
    this.drop(turnId)
    this.queue = this.queue.filter((q) => q.turnId !== turnId)
    if (this.current && this.current.item.turnId === turnId) this.cut(this.current)
  }

  /** Disconnected or another device took over: silence everything. */
  stopAll(): void {
    for (const q of this.queue) this.drop(q.turnId)
    this.queue = []
    if (this.current) {
      this.drop(this.current.item.turnId)
      this.cut(this.current)
    }
  }

  private cut(current: Current): void {
    current.stopped = true
    current.handle?.stop()
  }

  private drop(turnId: number): void {
    this.dropped.add(turnId)
    if (this.dropped.size > MAX_DROPPED) {
      const oldest = this.dropped.values().next().value
      if (oldest !== undefined) this.dropped.delete(oldest)
    }
  }

  private async pump(): Promise<void> {
    if (this.pumping) return
    this.pumping = true
    try {
      while (this.queue.length) {
        const item = this.queue.shift()!
        let buffer: AudioBuffer
        try {
          buffer = await item.buffer
        } catch {
          // couldn't decode: tell the server so it doesn't wait for it
          this.events.ended(item.turnId, item.seq, true)
          continue
        }
        if (this.dropped.has(item.turnId)) continue
        await this.playOne(item, buffer)
      }
    } finally {
      this.pumping = false
    }
  }

  private playOne(item: Item, buffer: AudioBuffer): Promise<void> {
    return new Promise((resolve) => {
      const current: Current = { item, handle: null, stopped: false }
      this.current = current
      this.events.started(item.turnId, item.seq)
      current.handle = this.out.play(buffer, () => {
        this.current = null
        this.lastEnd = performance.now()
        this.events.ended(item.turnId, item.seq, current.stopped)
        resolve()
      })
      if (current.stopped) current.handle.stop() // stopped while starting
    })
  }
}

/** The real output: Web Audio, with volume and an optional output device. */
export class WebAudioOut implements AudioOut {
  readonly ctx = new AudioContext()
  private readonly gain = this.ctx.createGain()

  constructor() {
    this.gain.connect(this.ctx.destination)
  }

  decode(mp3: ArrayBuffer): Promise<AudioBuffer> {
    return this.ctx.decodeAudioData(mp3)
  }

  play(buffer: AudioBuffer, onEnded: () => void): PlayHandle {
    if (this.ctx.state === 'suspended') void this.ctx.resume()
    const src = this.ctx.createBufferSource()
    src.buffer = buffer
    src.connect(this.gain)
    src.onended = () => {
      src.disconnect()
      onEnded()
    }
    src.start()
    return {
      stop: () => {
        try {
          src.stop()
        } catch {
          // already stopped
        }
      }
    }
  }

  setVolume(volume: number): void {
    this.gain.gain.value = volume
  }

  /** '' = system default output. */
  async setOutputDevice(deviceId: string): Promise<void> {
    const ctx = this.ctx as unknown as { setSinkId?: (id: string) => Promise<void> }
    if (ctx.setSinkId) await ctx.setSinkId(deviceId)
  }
}
