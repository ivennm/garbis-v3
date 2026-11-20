/** Types shared by the main, preload and renderer processes. */

export interface AppInfo {
  version: string
  platform: string // process.platform: 'darwin' | 'win32' | ...
  deviceName: string
}

/** Per-device settings, stored as settings.json in Electron's userData folder (ARCHITECTURE.md §4.5). */
export interface Settings {
  serverUrl: string
  token: string
  micDeviceId: string // '' = system default
  outputDeviceId: string // '' = system default
  volume: number // 0..1
  echoCancellation: boolean
  noiseSuppression: boolean
  autoGainControl: boolean
  alwaysOnTop: boolean
  desktopAudio: boolean // listen to guests in desktop audio (M3)
  desktopDeviceId: string // '' = system audio loopback; else an input device such as BlackHole
  startInTray: boolean // launch hidden; Garbis listens from the tray (M4)
  screenVision: boolean // send the main monitor every few seconds so Garbis can look when asked
}

/** A screenshot of the main monitor for screen vision (JPEG), or why there isn't one. */
export type ScreenCapture = { ok: true; jpeg: Uint8Array } | { ok: false; reason: string }

/** Window layouts: the face alone, the face + transcript, or settings. */
export type Layout = 'face' | 'transcript' | 'settings'

/** What the tray menu shows; the renderer pushes it whenever it changes. */
export interface TrayState {
  status: string // e.g. "Idle", "Can't reach the server, retrying…"
  online: boolean // connected and this device is the active one
  mode: 'low' | 'high'
  modeLoading: boolean
  muted: boolean
  desktopAudio: boolean
  screenVision: boolean
  transcriptOpen: boolean
}

/** Tray menu clicks that the renderer carries out (it owns the socket, mic and settings). */
export type TrayAction =
  | 'mode:low'
  | 'mode:high'
  | 'toggle-mute'
  | 'toggle-desktop'
  | 'toggle-screen'
  | 'toggle-transcript'

/** The preload API, exposed on `window.garbis` (ARCHITECTURE.md §4.2). */
export interface GarbisBridge {
  appInfo(): Promise<AppInfo>
  getSettings(): Promise<Settings>
  setSettings(patch: Partial<Settings>): Promise<Settings>
  /** Resizes the window for a layout (remembers the face-only size). */
  setLayout(layout: Layout): Promise<void>
  setTrayState(state: TrayState): void
  /** Screenshot of the main monitor, scaled to at most `maxWidth` px wide. */
  captureScreen(maxWidth: number): Promise<ScreenCapture>
  /** Returns an unsubscribe function. */
  onTrayAction(handler: (action: TrayAction) => void): () => void
  /** Settings were changed outside the renderer (the tray's "Start in the tray"). */
  onSettingsChanged(handler: () => void): () => void
}
