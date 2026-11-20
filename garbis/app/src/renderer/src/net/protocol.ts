/**
 * Wire format between the app and the server (ARCHITECTURE.md §5).
 * Mirrors server/garbis_server/protocol.py; bump PROTOCOL_VERSION on both sides together.
 */

export const PROTOCOL_VERSION = 1
export const MIC = 0x01 // app -> server: 16 kHz mono int16 LE, 20 ms per frame
export const DESKTOP = 0x02 // app -> server: same, desktop audio
export const CLIP = 0x10 // server -> app: u8 type, u32 LE turn_id, u16 LE seq, mp3 bytes
export const FRAME_SAMPLES = 320
const CLIP_HEADER = 7

export type FaceState = 'idle' | 'listen' | 'think' | 'speak'
export type Mode = 'low' | 'high'
export type ModeStatus = 'loading' | 'ready'
export type HeardAction = 'reply' | 'followup' | 'ignored' | 'stop' | 'merged' | 'command'

export type ServerMessage =
  | { type: 'welcome'; server_version: string; protocol: number; mode: Mode; mode_status: ModeStatus; model: string }
  | { type: 'session'; active: boolean; active_device: string | null }
  | { type: 'state'; state: FaceState; source: string | null }
  | { type: 'heard'; source: string; text: string; action: HeardAction }
  | { type: 'say'; turn_id: number; seq: number; text: string }
  | { type: 'turn_end'; turn_id: number }
  | { type: 'stop_audio'; turn_id: number }
  | { type: 'mode'; mode: Mode; status: ModeStatus; model: string }
  | {
      type: 'timing'
      turn_id: number
      heard_s: number
      first_text_s: number
      first_audio_s: number
      total_s: number
    }
  | { type: 'error'; code: string; message: string }

export interface Hello {
  type: 'hello'
  token: string
  protocol: number
  device_name: string
  os: string
  app_version: string
}

export type ClientMessage =
  | Hello
  | { type: 'take_over' }
  | { type: 'set_mode'; mode: Mode }
  | { type: 'clip_started'; turn_id: number; seq: number }
  | { type: 'clip_ended'; turn_id: number; seq: number; interrupted: boolean }
  | { type: 'mic_muted'; muted: boolean }

/** Error codes after which the server closes the socket and retrying won't help. */
export const REFUSAL_CODES = new Set(['bad_token', 'protocol_mismatch', 'bad_hello'])

export function packAudio(type: number, pcm: ArrayBuffer): ArrayBuffer {
  const out = new Uint8Array(1 + pcm.byteLength)
  out[0] = type
  out.set(new Uint8Array(pcm), 1)
  return out.buffer
}

export interface Clip {
  turnId: number
  seq: number
  mp3: ArrayBuffer
}

export function unpackClip(buf: ArrayBuffer): Clip | null {
  if (buf.byteLength < CLIP_HEADER) return null
  const view = new DataView(buf)
  if (view.getUint8(0) !== CLIP) return null
  return { turnId: view.getUint32(1, true), seq: view.getUint16(5, true), mp3: buf.slice(CLIP_HEADER) }
}
