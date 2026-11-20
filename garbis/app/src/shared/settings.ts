import type { Settings } from './types'

export const DEFAULT_SETTINGS: Settings = {
  serverUrl: 'ws://mc-server:8765/ws', // Tailscale MagicDNS name: works at home and away
  token: '',
  micDeviceId: '',
  outputDeviceId: '',
  volume: 1,
  // Off like v2 (use headphones). On, Chromium's echo canceller swallowed "garbis, stop" while Garbis
  // was talking in testing (2026-11-19); only turn it on if you use speakers.
  echoCancellation: false,
  noiseSuppression: true,
  autoGainControl: false,
  alwaysOnTop: false,
  desktopAudio: true,
  desktopDeviceId: '',
  startInTray: false,
  screenVision: true // "always watching" (2026-11-20): Garbis only looks when asked
}

/** Merges anything (a parsed settings file, a patch) onto the defaults, keeping only well-typed fields. */
export function sanitizeSettings(raw: unknown, base: Settings = DEFAULT_SETTINGS): Settings {
  const out: Settings = { ...base }
  if (!raw || typeof raw !== 'object') return out
  const src = raw as Record<string, unknown>
  for (const key of Object.keys(DEFAULT_SETTINGS) as (keyof Settings)[]) {
    const value = src[key]
    if (typeof value === typeof DEFAULT_SETTINGS[key]) {
      ;(out as unknown as Record<string, unknown>)[key] = value
    }
  }
  out.volume = Number.isFinite(out.volume) ? Math.min(1, Math.max(0, out.volume)) : DEFAULT_SETTINGS.volume
  out.serverUrl = out.serverUrl.trim() || DEFAULT_SETTINGS.serverUrl
  return out
}
