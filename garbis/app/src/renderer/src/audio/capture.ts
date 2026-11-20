/**
 * Audio in: any MediaStream -> 16 kHz AudioContext -> pcm16k worklet -> 20 ms int16 frames.
 * Chromium resamples the input to the context's 16 kHz itself. Desktop audio (M3) reuses capture().
 */
import workletSource from './pcm16k.worklet.js?raw'

export interface Capture {
  stop(): void
}

export interface MicOptions {
  micDeviceId: string
  echoCancellation: boolean
  noiseSuppression: boolean
  autoGainControl: boolean
}

let contextPromise: Promise<AudioContext> | null = null

function captureContext(): Promise<AudioContext> {
  if (!contextPromise) {
    contextPromise = (async () => {
      const ctx = new AudioContext({ sampleRate: 16000 })
      const url = URL.createObjectURL(new Blob([workletSource], { type: 'text/javascript' }))
      try {
        await ctx.audioWorklet.addModule(url)
      } finally {
        URL.revokeObjectURL(url)
      }
      return ctx
    })()
    contextPromise.catch(() => {
      contextPromise = null // let the next attempt try again
    })
  }
  return contextPromise
}

export async function capture(
  stream: MediaStream,
  onFrame: (pcm: ArrayBuffer) => void,
  onLevel: (peak: number) => void
): Promise<Capture> {
  const ctx = await captureContext()
  if (ctx.state === 'suspended') await ctx.resume()
  const source = ctx.createMediaStreamSource(stream)
  const node = new AudioWorkletNode(ctx, 'pcm16k')
  const sink = ctx.createGain()
  sink.gain.value = 0 // keeps the worklet pulled by the graph without playing anything
  source.connect(node)
  node.connect(sink)
  sink.connect(ctx.destination)
  node.port.onmessage = (event: MessageEvent<{ pcm: ArrayBuffer; peak: number }>) => {
    onLevel(event.data.peak)
    onFrame(event.data.pcm)
  }
  return {
    stop() {
      node.port.onmessage = null
      source.disconnect()
      node.disconnect()
      sink.disconnect()
      stream.getTracks().forEach((t) => t.stop())
    }
  }
}

export async function startMic(
  opts: MicOptions,
  onFrame: (pcm: ArrayBuffer) => void,
  onLevel: (peak: number) => void
): Promise<Capture> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      deviceId: opts.micDeviceId ? { exact: opts.micDeviceId } : undefined,
      echoCancellation: opts.echoCancellation,
      noiseSuppression: opts.noiseSuppression,
      autoGainControl: opts.autoGainControl,
      channelCount: 1
    }
  })
  return capture(stream, onFrame, onLevel)
}
