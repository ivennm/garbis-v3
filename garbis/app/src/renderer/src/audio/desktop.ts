/**
 * Desktop (guest) audio in (ARCHITECTURE.md §4.3), through the same 16 kHz worklet as the mic.
 *
 * Default: system-audio loopback via getDisplayMedia(). The main process answers it with no picker.
 * Override: an input device (e.g. BlackHole) via getUserMedia, for when loopback isn't available.
 */
import { capture } from './capture'
import type { Capture } from './capture'

export type DesktopProblem = 'unsupported' | 'blocked' | 'no-audio' | 'not-found' | 'failed'

export class DesktopAudioError extends Error {
  constructor(
    readonly problem: DesktopProblem,
    message: string
  ) {
    super(message)
  }
}

const RAW: MediaTrackConstraints = { echoCancellation: false, noiseSuppression: false, autoGainControl: false }

async function loopbackStream(): Promise<MediaStream> {
  if (!navigator.mediaDevices.getDisplayMedia) {
    throw new DesktopAudioError('unsupported', 'Desktop audio capture is not available here')
  }
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: true, // required by the API; dropped right away
    // restrictOwnAudio asks Chromium to leave this app's own playback (Garbis's voice) out of the
    // loopback where supported. Echo gating covers it either way.
    audio: { ...RAW, restrictOwnAudio: true } as MediaTrackConstraints
  })
  for (const track of stream.getVideoTracks()) {
    track.stop()
    stream.removeTrack(track)
  }
  return stream
}

async function deviceStream(deviceId: string): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({ audio: { ...RAW, deviceId: { exact: deviceId }, channelCount: 2 } })
}

export interface DesktopCapture extends Capture {
  /** Fires if the source dies later (device unplugged, permission revoked). */
  onEnded(handler: () => void): void
}

export async function startDesktop(
  deviceId: string,
  onFrame: (pcm: ArrayBuffer) => void,
  onLevel: (peak: number) => void
): Promise<DesktopCapture> {
  let stream: MediaStream
  try {
    stream = deviceId ? await deviceStream(deviceId) : await loopbackStream()
  } catch (e) {
    if (e instanceof DesktopAudioError) throw e
    const err = e as DOMException
    if (err.name === 'NotAllowedError') throw new DesktopAudioError('blocked', 'Desktop audio was refused')
    if (err.name === 'NotFoundError' || err.name === 'OverconstrainedError') {
      throw new DesktopAudioError('not-found', 'Desktop audio device not found')
    }
    throw new DesktopAudioError('failed', `Desktop audio error: ${err.message}`)
  }

  const track = stream.getAudioTracks()[0]
  if (!track) {
    stream.getTracks().forEach((t) => t.stop())
    throw new DesktopAudioError('no-audio', 'No audio in the desktop capture')
  }
  // macOS: a missing System Audio Recording permission gives a track that is already ended
  // and never delivers samples, with no error (Electron desktopCapturer docs).
  if (track.readyState === 'ended') {
    throw new DesktopAudioError('blocked', 'Desktop audio is blocked by macOS')
  }

  const cap = await capture(stream, onFrame, onLevel)
  let endedHandler: (() => void) | null = null
  let stopped = false
  track.addEventListener('ended', () => {
    if (!stopped) endedHandler?.()
  })
  return {
    stop() {
      stopped = true
      cap.stop()
    },
    onEnded(handler) {
      endedHandler = handler
    }
  }
}
