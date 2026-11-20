/**
 * Screen vision (2026-11-20): a JPEG of the MAIN monitor, scaled down (768 px wide reads text well and keeps
 * the vision model at ~4 s on the GTX 1650). The renderer sends one every few seconds and on request; the
 * server only keeps the latest in RAM and only looks at it when you ask about your screen.
 *
 * macOS: needs the Screen & System Audio Recording permission. Without it, desktopCapturer returns only the
 * wallpaper or nothing, so this reports "not allowed" instead of sending a useless picture.
 */
import { desktopCapturer, screen, systemPreferences } from 'electron'
import type { ScreenCapture } from '../shared/types'

export async function captureMainScreen(maxWidth: number): Promise<ScreenCapture> {
  if (process.platform === 'darwin' && systemPreferences.getMediaAccessStatus('screen') === 'denied') {
    return { ok: false, reason: 'Screen Recording is not allowed for Garbis (System Settings > Privacy & Security)' }
  }
  try {
    const primary = screen.getPrimaryDisplay()
    const { width, height } = primary.size
    const scale = Math.min(1, maxWidth / width)
    const sources = await desktopCapturer.getSources({
      types: ['screen'],
      thumbnailSize: { width: Math.round(width * scale), height: Math.round(height * scale) }
    })
    const source = sources.find((s) => s.display_id === String(primary.id)) ?? sources[0]
    if (!source || source.thumbnail.isEmpty()) return { ok: false, reason: 'no screen image available' }
    return { ok: true, jpeg: new Uint8Array(source.thumbnail.toJPEG(75)) }
  } catch (e) {
    return { ok: false, reason: `screen capture failed: ${(e as Error).message}` }
  }
}
