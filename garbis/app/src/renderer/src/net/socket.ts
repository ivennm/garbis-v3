/**
 * One WebSocket to the Garbis server that keeps itself connected (ARCHITECTURE.md §4.6).
 * Sends `hello` on every connect; reconnects with backoff 0.5 s -> 5 s; stops retrying if refused.
 */
import { REFUSAL_CODES, unpackClip } from './protocol'
import type { ClientMessage, Clip, Hello, ServerMessage } from './protocol'

export type ConnStatus = 'connecting' | 'online' | 'offline' | 'refused'

export const FIRST_RETRY_MS = 500
export const MAX_RETRY_MS = 5000
/** Audio is dropped rather than queued once this much is waiting to go out (a stalled link). */
const MAX_BUFFERED_BYTES = 256 * 1024

export function nextDelay(prev: number): number {
  return prev <= 0 ? FIRST_RETRY_MS : Math.min(prev * 2, MAX_RETRY_MS)
}

export interface SocketOptions {
  url: string
  hello: Omit<Hello, 'type'>
  onMessage(msg: ServerMessage): void
  onClip(clip: Clip): void
  onStatus(status: ConnStatus, detail?: string): void
  /** For tests. */
  WebSocketImpl?: typeof WebSocket
}

export class GarbisSocket {
  private ws: WebSocket | null = null
  private delay = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private stopped = true
  private refused = false
  private welcomed = false

  constructor(private readonly opts: SocketOptions) {}

  start(): void {
    this.stopped = false
    this.refused = false
    this.delay = 0
    this.open()
  }

  stop(): void {
    this.stopped = true
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    const ws = this.ws
    this.ws = null
    this.welcomed = false
    ws?.close()
  }

  /** Connected and accepted by the server (welcome received). */
  get ready(): boolean {
    return this.welcomed && this.ws?.readyState === 1
  }

  send(msg: ClientMessage): void {
    if (this.ready) this.ws!.send(JSON.stringify(msg))
  }

  sendBinary(data: ArrayBuffer): void {
    if (this.ready && this.ws!.bufferedAmount < MAX_BUFFERED_BYTES) this.ws!.send(data)
  }

  private open(): void {
    const Impl = this.opts.WebSocketImpl ?? WebSocket
    this.opts.onStatus('connecting')
    let ws: WebSocket
    try {
      ws = new Impl(this.opts.url)
    } catch (e) {
      // e.g. a malformed address in settings
      this.refused = true
      this.opts.onStatus('refused', `Bad server address: ${(e as Error).message}`)
      return
    }
    this.ws = ws
    ws.binaryType = 'arraybuffer'

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'hello', ...this.opts.hello }))
    }

    ws.onmessage = (event: MessageEvent) => {
      if (ws !== this.ws) return
      if (typeof event.data !== 'string') {
        const clip = unpackClip(event.data as ArrayBuffer)
        if (clip) this.opts.onClip(clip)
        return
      }
      let msg: ServerMessage
      try {
        msg = JSON.parse(event.data) as ServerMessage
      } catch {
        return
      }
      if (msg.type === 'welcome') {
        this.welcomed = true
        this.delay = 0
        this.opts.onStatus('online')
      } else if (msg.type === 'error' && REFUSAL_CODES.has(msg.code)) {
        this.refused = true
        this.opts.onStatus('refused', msg.message)
      }
      this.opts.onMessage(msg)
    }

    ws.onclose = () => {
      if (ws !== this.ws) return // an old socket we already replaced
      this.ws = null
      this.welcomed = false
      if (this.stopped || this.refused) return
      this.opts.onStatus('offline')
      this.delay = nextDelay(this.delay)
      this.timer = setTimeout(() => this.open(), this.delay)
    }
  }
}
