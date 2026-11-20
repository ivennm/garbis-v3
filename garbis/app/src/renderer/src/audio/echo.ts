/**
 * Echo gating for desktop audio (ARCHITECTURE.md §4.3): loopback hears Garbis's own voice, so
 * desktop frames aren't sent while a clip plays or for a short tail after. The app knows the
 * exact playback times; the server's own mute rule is only a backup.
 */
export const DESKTOP_TAIL_MS = 600 // matches the server's DESKTOP_TAIL_S

export function desktopGated(playing: boolean, lastEnd: number, now: number, tailMs = DESKTOP_TAIL_MS): boolean {
  return playing || (lastEnd > 0 && now - lastEnd < tailMs)
}
