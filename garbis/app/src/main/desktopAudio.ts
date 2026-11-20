/**
 * Desktop (guest) audio: answer the renderer's getDisplayMedia() with the primary screen plus
 * system-audio loopback, so there's no picker and no prompt every session (ARCHITECTURE.md §4.3).
 *
 * - Windows: WASAPI loopback.
 * - macOS 14.2+: Chromium's CoreAudio Tap, the default since Electron 39 (no feature flags).
 *   Needs NSAudioCaptureUsageDescription in Info.plist (electron-builder.yml). If the permission
 *   is missing, the audio track arrives already "ended"; the renderer checks for that.
 *   Unpackaged (`npm run dev`), macOS asks on behalf of the parent app (Terminal/VS Code), which
 *   usually lacks that key, so desktop audio may only work in the packaged app.
 * The video track is only there because the API needs one; the renderer stops it at once.
 */
import { desktopCapturer } from 'electron'
import type { Session } from 'electron'

export function setupDesktopAudio(ses: Session): void {
  ses.setDisplayMediaRequestHandler(async (_request, callback) => {
    try {
      const sources = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: 0, height: 0 } })
      if (!sources.length) {
        console.warn('desktop audio: no screen source available')
        callback(null)
        return
      }
      callback({ video: sources[0], audio: 'loopback' })
    } catch (e) {
      console.warn('desktop audio: could not get a screen source:', e)
      callback(null)
    }
  })
}
