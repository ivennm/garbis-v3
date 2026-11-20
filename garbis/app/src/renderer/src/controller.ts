/**
 * Wires the socket, the mic and the player together and keeps the store up to date.
 * Components call its actions; nothing else talks to the server.
 */
import type { AppInfo, Settings, TrayAction, TrayState } from '../../shared/types'
import { startMic } from './audio/capture'
import type { Capture } from './audio/capture'
import { DesktopAudioError, startDesktop } from './audio/desktop'
import type { DesktopCapture } from './audio/desktop'
import { desktopGated } from './audio/echo'
import { ClipPlayer, WebAudioOut } from './audio/player'
import { DESKTOP, MIC, PROTOCOL_VERSION, packAudio, packScreen } from './net/protocol'
import type { Mode, ServerMessage } from './net/protocol'
import { GarbisSocket } from './net/socket'
import { addEntry, addSaid, describe, useGarbis } from './state/store'
import type { Panel } from './state/store'

const MIC_KEYS: (keyof Settings)[] = ['micDeviceId', 'echoCancellation', 'noiseSuppression', 'autoGainControl']
const DESKTOP_KEYS: (keyof Settings)[] = ['desktopAudio', 'desktopDeviceId']
const LEVEL_INTERVAL_MS = 80
const DESKTOP_RETRY_MS = 5000
const SCREEN_EVERY_MS = 5000 // "always watching": the server keeps only the latest one, in RAM
const SCREEN_WIDTH = 768 // reads text fine and keeps the vision model quick (tested 2026-11-20)

/** Peak level, pushed to the store at most every LEVEL_INTERVAL_MS (meters don't need 50 updates/s). */
function levelMeter(key: 'micLevel' | 'desktopLevel'): (peak: number) => void {
  let peak = 0
  let last = 0
  return (p) => {
    peak = Math.max(peak, p)
    const now = performance.now()
    if (now - last >= LEVEL_INTERVAL_MS) {
      useGarbis.setState({ [key]: peak })
      peak = 0
      last = now
    }
  }
}

function desktopProblemText(e: unknown, platform: string, viaDevice: boolean): string {
  if (!(e instanceof DesktopAudioError)) return `Desktop audio error: ${(e as Error).message}`
  if (e.problem === 'blocked' && platform === 'darwin' && !viaDevice) {
    return (
      'Desktop audio is blocked. Allow Garbis in System Settings > Privacy & Security > ' +
      'Screen & System Audio Recording. (Running with npm run dev? Use the packaged app, or BlackHole as the source.)'
    )
  }
  if (e.problem === 'not-found') return 'Desktop audio device not found: pick another source'
  return e.message
}

class Controller {
  private info!: AppInfo
  private settings!: Settings
  private socket: GarbisSocket | null = null
  private out!: WebAudioOut
  private player!: ClipPlayer
  private mic: Capture | null = null
  private micGeneration = 0
  private desktop: DesktopCapture | null = null
  private desktopGeneration = 0
  private desktopRetry: ReturnType<typeof setTimeout> | null = null
  private started = false
  private lastTray = ''
  private capturing = false
  private readonly onMicLevel = levelMeter('micLevel')
  private readonly onDesktopLevel = levelMeter('desktopLevel')

  async start(): Promise<void> {
    if (this.started) return
    this.started = true
    ;[this.info, this.settings] = await Promise.all([window.garbis.appInfo(), window.garbis.getSettings()])
    useGarbis.setState({ settings: this.settings })

    this.out = new WebAudioOut()
    this.out.setVolume(this.settings.volume)
    await this.applyOutputDevice()
    this.player = new ClipPlayer(this.out, {
      started: (turn_id, seq) => this.socket?.send({ type: 'clip_started', turn_id, seq }),
      ended: (turn_id, seq, interrupted) => this.socket?.send({ type: 'clip_ended', turn_id, seq, interrupted })
    })

    window.garbis.onTrayAction((action) => void this.onTrayAction(action))
    window.garbis.onSettingsChanged(() => void this.reloadSettings())
    useGarbis.subscribe(() => this.pushTrayState())
    this.pushTrayState()

    this.connect()
    setInterval(() => void this.sendScreen(0), SCREEN_EVERY_MS) // runs for the app's lifetime
    await this.restartMic()
    await this.restartDesktop()
  }

  // ---- actions (called from components) ----

  toggleMute(): void {
    const muted = !useGarbis.getState().muted
    useGarbis.setState({ muted })
    this.socket?.send({ type: 'mic_muted', muted })
  }

  setMode(mode: Mode): void {
    this.socket?.send({ type: 'set_mode', mode })
  }

  takeOver(): void {
    this.socket?.send({ type: 'take_over' })
  }

  async openPanel(panel: Panel): Promise<void> {
    useGarbis.setState({ panel })
    await window.garbis.setLayout(panel === 'none' ? 'face' : panel)
  }

  async togglePanel(panel: Exclude<Panel, 'none'>): Promise<void> {
    await this.openPanel(useGarbis.getState().panel === panel ? 'none' : panel)
  }

  // ---- tray (M4) ----

  private async onTrayAction(action: TrayAction): Promise<void> {
    switch (action) {
      case 'mode:low':
      case 'mode:high':
        this.setMode(action === 'mode:low' ? 'low' : 'high')
        break
      case 'toggle-mute':
        this.toggleMute()
        break
      case 'toggle-desktop':
        await this.toggleDesktop()
        break
      case 'toggle-screen':
        await this.toggleScreen()
        break
      case 'toggle-transcript':
        await this.togglePanel('transcript')
        break
    }
  }

  private pushTrayState(): void {
    const s = useGarbis.getState()
    const state: TrayState = {
      status: describe(s).status,
      online: s.conn === 'online' && s.active,
      mode: s.mode,
      modeLoading: s.modeStatus === 'loading',
      muted: s.muted,
      desktopAudio: s.settings?.desktopAudio ?? false,
      screenVision: s.settings?.screenVision ?? false,
      transcriptOpen: s.panel === 'transcript'
    }
    const key = JSON.stringify(state)
    if (key === this.lastTray) return // the store changes ~12x/s with the level meters
    this.lastTray = key
    window.garbis.setTrayState(state)
  }

  private async reloadSettings(): Promise<void> {
    this.settings = await window.garbis.getSettings()
    useGarbis.setState({ settings: this.settings })
  }

  async updateSettings(patch: Partial<Settings>): Promise<void> {
    const prev = this.settings
    this.settings = await window.garbis.setSettings(patch)
    useGarbis.setState({ settings: this.settings })
    const changed = (k: keyof Settings): boolean => prev[k] !== this.settings[k]
    if (changed('serverUrl') || changed('token')) this.connect()
    if (MIC_KEYS.some(changed)) await this.restartMic()
    if (DESKTOP_KEYS.some(changed)) await this.restartDesktop()
    if (changed('volume')) this.out.setVolume(this.settings.volume)
    if (changed('outputDeviceId')) await this.applyOutputDevice()
  }

  // ---- connection ----

  private connect(): void {
    this.socket?.stop()
    this.player?.stopAll()
    this.socket = new GarbisSocket({
      url: this.settings.serverUrl,
      hello: {
        token: this.settings.token,
        protocol: PROTOCOL_VERSION,
        device_name: this.info.deviceName,
        os: this.info.platform,
        app_version: this.info.version
      },
      onMessage: (m) => this.onMessage(m),
      onClip: ({ turnId, seq, mp3 }) => this.player.add(turnId, seq, mp3),
      onStatus: (conn, detail) => {
        useGarbis.setState({ conn, connDetail: detail ?? null })
        if (conn !== 'online') {
          this.player.stopAll()
          useGarbis.setState({ active: false, face: 'idle', source: null })
        }
      }
    })
    this.socket.start()
  }

  private onMessage(m: ServerMessage): void {
    switch (m.type) {
      case 'welcome':
        useGarbis.setState({ mode: m.mode, modeStatus: m.mode_status, model: m.model })
        this.socket?.send({ type: 'mic_muted', muted: useGarbis.getState().muted })
        break
      case 'session':
        useGarbis.setState({ active: m.active, activeDevice: m.active_device })
        if (!m.active) {
          this.player.stopAll()
          useGarbis.setState({ face: 'idle', source: null })
        }
        break
      case 'state':
        useGarbis.setState({ face: m.state, source: m.source })
        break
      case 'heard':
        addEntry('heard', m.text, { source: m.source, action: m.action })
        break
      case 'say':
        addSaid(m.turn_id, m.text)
        break
      case 'stop_audio':
        this.player.stop(m.turn_id)
        break
      case 'turn_end':
        break
      case 'mode':
        useGarbis.setState({ mode: m.mode, modeStatus: m.status, model: m.model })
        break
      case 'timing':
        addEntry(
          'timing',
          `${m.total_s.toFixed(2)} s · heard ${m.heard_s.toFixed(2)} · first words ${m.first_text_s.toFixed(2)} · voice ${m.first_audio_s.toFixed(2)}`,
          { turnId: m.turn_id }
        )
        break
      case 'error':
        addEntry('error', `${m.code}: ${m.message}`)
        break
      case 'capture_screen':
        void this.sendScreen(m.request_id)
        break
    }
  }

  // ---- audio ----

  private sendMicFrame = (pcm: ArrayBuffer): void => {
    const s = useGarbis.getState()
    if (s.muted || !s.active) return
    this.socket?.sendBinary(packAudio(MIC, pcm))
  }

  private sendDesktopFrame = (pcm: ArrayBuffer): void => {
    if (!useGarbis.getState().active || !this.settings.desktopAudio) return
    // Garbis's own voice comes back through loopback: don't send it (ARCHITECTURE.md §4.3)
    if (desktopGated(this.player.playing, this.player.lastEnd, performance.now())) return
    this.socket?.sendBinary(packAudio(DESKTOP, pcm))
  }

  // ---- screen vision (2026-11-20) ----

  async toggleScreen(): Promise<void> {
    await this.updateSettings({ screenVision: !this.settings.screenVision })
    if (!this.settings.screenVision) useGarbis.setState({ screenLive: false, screenError: null })
    else void this.sendScreen(0)
  }

  /** requestId 0 = the regular "always watching" shot; otherwise the server asked for a fresh one. */
  private async sendScreen(requestId: number): Promise<void> {
    const s = useGarbis.getState()
    const refuse = (reason: string) => {
      if (requestId) this.socket?.send({ type: 'screen_unavailable', request_id: requestId, reason })
    }
    if (!this.settings.screenVision) return refuse('screen vision is off in the app')
    if (s.conn !== 'online' || !s.active || !this.socket?.ready) return
    if (this.capturing && requestId === 0) return // a regular shot can wait for the next tick
    this.capturing = true
    try {
      const shot = await window.garbis.captureScreen(SCREEN_WIDTH)
      if (!shot.ok) {
        useGarbis.setState({ screenLive: false, screenError: shot.reason })
        return refuse(shot.reason)
      }
      const frame = packScreen(requestId, shot.jpeg)
      if (requestId) this.socket?.sendBinaryAlways(frame)
      else this.socket?.sendBinary(frame)
      if (!s.screenLive || s.screenError) useGarbis.setState({ screenLive: true, screenError: null })
    } finally {
      this.capturing = false
    }
  }

  async toggleDesktop(): Promise<void> {
    await this.updateSettings({ desktopAudio: !this.settings.desktopAudio })
  }

  private async restartDesktop(): Promise<void> {
    const generation = ++this.desktopGeneration
    if (this.desktopRetry) clearTimeout(this.desktopRetry)
    this.desktopRetry = null
    this.desktop?.stop()
    this.desktop = null
    useGarbis.setState({ desktopLive: false, desktopLevel: 0 })
    if (!this.settings.desktopAudio) {
      useGarbis.setState({ desktopError: null })
      return
    }
    try {
      const desktop = await startDesktop(this.settings.desktopDeviceId, this.sendDesktopFrame, this.onDesktopLevel)
      if (generation !== this.desktopGeneration) {
        desktop.stop()
        return
      }
      this.desktop = desktop
      useGarbis.setState({ desktopLive: true, desktopError: null })
      desktop.onEnded(() => {
        if (generation !== this.desktopGeneration) return
        useGarbis.setState({ desktopLive: false, desktopError: 'Desktop audio stopped, retrying…' })
        this.desktopRetry = setTimeout(() => void this.restartDesktop(), DESKTOP_RETRY_MS)
      })
    } catch (e) {
      if (generation !== this.desktopGeneration) return
      const why = desktopProblemText(e, this.info.platform, Boolean(this.settings.desktopDeviceId))
      useGarbis.setState({ desktopLive: false, desktopError: why })
      addEntry('error', why)
    }
  }

  private async restartMic(): Promise<void> {
    const generation = ++this.micGeneration // a newer restart wins if two overlap
    this.mic?.stop()
    this.mic = null
    try {
      const mic = await startMic(this.settings, this.sendMicFrame, this.onMicLevel)
      if (generation !== this.micGeneration) {
        mic.stop()
        return
      }
      this.mic = mic
      useGarbis.setState({ micError: null })
    } catch (e) {
      const err = e as DOMException
      const why =
        err.name === 'NotAllowedError'
          ? 'Mic blocked: allow Garbis in System Settings > Privacy > Microphone'
          : err.name === 'NotFoundError' || err.name === 'OverconstrainedError'
            ? 'Mic not found: pick another one in settings'
            : `Mic error: ${err.message}`
      useGarbis.setState({ micError: why })
      addEntry('error', why)
    }
  }

  private async applyOutputDevice(): Promise<void> {
    try {
      await this.out.setOutputDevice(this.settings.outputDeviceId)
    } catch (e) {
      addEntry('error', `Output device unavailable, using the default: ${(e as Error).message}`)
      await this.out.setOutputDevice('').catch(() => undefined)
    }
  }
}

export const controller = new Controller()
