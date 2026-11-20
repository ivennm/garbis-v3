import { afterEach, describe, expect, it, vi } from 'vitest'
import { CLIP, MIC, packAudio, unpackClip } from './protocol'
import { GarbisSocket, MAX_RETRY_MS, nextDelay } from './socket'
import type { ConnStatus } from './socket'

describe('protocol', () => {
  it('packs a mic frame as type byte + int16 samples', () => {
    const pcm = new Int16Array([1, -1, 32767, -32768]).buffer
    const bytes = new Uint8Array(packAudio(MIC, pcm))
    expect(bytes.length).toBe(9)
    expect(bytes[0]).toBe(MIC)
    expect(Array.from(new Int16Array(bytes.slice(1).buffer))).toEqual([1, -1, 32767, -32768])
  })

  it('unpacks a clip frame laid out like protocol.py pack_clip (<BIH + mp3)', () => {
    const buf = new ArrayBuffer(7 + 3)
    const v = new DataView(buf)
    v.setUint8(0, CLIP)
    v.setUint32(1, 70000, true)
    v.setUint16(5, 3, true)
    new Uint8Array(buf, 7).set([0xff, 0xfb, 0x90])
    const clip = unpackClip(buf)!
    expect(clip.turnId).toBe(70000)
    expect(clip.seq).toBe(3)
    expect(Array.from(new Uint8Array(clip.mp3))).toEqual([0xff, 0xfb, 0x90])
  })

  it('packs a screenshot like protocol.py parse_screen expects (<BI + JPEG)', async () => {
    const { SCREEN, packScreen } = await import('./protocol')
    const jpeg = new Uint8Array([0xff, 0xd8, 1, 2, 3])
    const v = new DataView(packScreen(42, jpeg))
    expect(v.getUint8(0)).toBe(SCREEN)
    expect(v.getUint32(1, true)).toBe(42)
    expect(Array.from(new Uint8Array(v.buffer, 5))).toEqual([0xff, 0xd8, 1, 2, 3])
  })

  it('rejects frames that are not clips', () => {
    expect(unpackClip(new Uint8Array([MIC, 0, 0, 0, 0, 0, 0]).buffer)).toBeNull()
    expect(unpackClip(new ArrayBuffer(3))).toBeNull()
  })
})

describe('reconnect backoff', () => {
  it('starts at 0.5 s and doubles up to 5 s', () => {
    const delays: number[] = []
    let d = 0
    for (let i = 0; i < 7; i++) delays.push((d = nextDelay(d)))
    expect(delays).toEqual([500, 1000, 2000, 4000, 5000, 5000, 5000])
    expect(Math.max(...delays)).toBe(MAX_RETRY_MS)
  })
})

/** Minimal WebSocket stand-in driven by the test. */
class FakeWebSocket {
  static instances: FakeWebSocket[] = []
  readyState = 0
  binaryType = 'blob'
  bufferedAmount = 0
  sent: unknown[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: unknown }) => void) | null = null
  onclose: (() => void) | null = null
  constructor(public url: string) {
    FakeWebSocket.instances.push(this)
  }
  send(data: unknown) {
    this.sent.push(typeof data === 'string' ? JSON.parse(data) : data)
  }
  close() {
    this.readyState = 3
    this.onclose?.()
  }
  // test helpers
  open() {
    this.readyState = 1
    this.onopen?.()
  }
  receive(obj: object) {
    this.onmessage?.({ data: JSON.stringify(obj) })
  }
  drop() {
    this.readyState = 3
    this.onclose?.()
  }
}

function makeSocket() {
  FakeWebSocket.instances = []
  const statuses: string[] = []
  const messages: string[] = []
  const socket = new GarbisSocket({
    url: 'ws://test/ws',
    hello: { token: 't', protocol: 1, device_name: 'mac', os: 'darwin', app_version: '0.1.0' },
    onMessage: (m) => messages.push(m.type),
    onClip: () => undefined,
    onStatus: (s: ConnStatus, d?: string) => statuses.push(d ? `${s}: ${d}` : s),
    WebSocketImpl: FakeWebSocket as unknown as typeof WebSocket
  })
  return { socket, statuses, messages }
}

describe('GarbisSocket', () => {
  afterEach(() => vi.useRealTimers())

  it('says hello on open and is ready after welcome', () => {
    const { socket, statuses } = makeSocket()
    socket.start()
    const ws = FakeWebSocket.instances[0]
    ws.open()
    expect(ws.sent[0]).toMatchObject({ type: 'hello', token: 't', device_name: 'mac', protocol: 1 })
    expect(socket.ready).toBe(false)
    ws.receive({ type: 'welcome', server_version: '0.1.0', protocol: 1, mode: 'low', mode_status: 'ready', model: 'x' })
    expect(socket.ready).toBe(true)
    expect(statuses).toEqual(['connecting', 'online'])
  })

  it('reconnects with backoff after the server goes away', () => {
    vi.useFakeTimers()
    const { socket, statuses } = makeSocket()
    socket.start()
    FakeWebSocket.instances[0].drop()
    expect(statuses).toEqual(['connecting', 'offline'])
    vi.advanceTimersByTime(499)
    expect(FakeWebSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(2)
    FakeWebSocket.instances[1].drop()
    vi.advanceTimersByTime(999)
    expect(FakeWebSocket.instances).toHaveLength(2)
    vi.advanceTimersByTime(1)
    expect(FakeWebSocket.instances).toHaveLength(3)
  })

  it('stops retrying when the token is wrong', () => {
    vi.useFakeTimers()
    const { socket, statuses } = makeSocket()
    socket.start()
    const ws = FakeWebSocket.instances[0]
    ws.open()
    ws.receive({ type: 'error', code: 'bad_token', message: 'wrong token' })
    ws.drop()
    vi.advanceTimersByTime(10_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
    expect(statuses.at(-1)).toBe('refused: wrong token')
  })

  it('does not reconnect after stop()', () => {
    vi.useFakeTimers()
    const { socket } = makeSocket()
    socket.start()
    socket.stop()
    vi.advanceTimersByTime(10_000)
    expect(FakeWebSocket.instances).toHaveLength(1)
  })
})
