/**
 * Electron main process: the window and app lifecycle (ARCHITECTURE.md §4.2).
 * M2: hardened window, settings, mic permission. M3: desktop audio. M4: tray, layouts, icons.
 *
 * Closing the window hides it: Garbis keeps listening from the tray. Quit is in the tray menu
 * (and Cmd+Q on macOS).
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { hostname } from 'node:os'
import { app, BrowserWindow, ipcMain, nativeImage, session, shell, systemPreferences } from 'electron'
import appIcon from '../../resources/icon.png?asset'
import type { AppInfo, Layout, Settings, TrayAction, TrayState } from '../shared/types'
import { setupDesktopAudio } from './desktopAudio'
import { captureMainScreen } from './screenCapture'
import { loadSettings, saveSettings } from './settings'
import { GarbisTray } from './tray'

const BG = '#1e1e2f'
const LAYOUTS: Record<Layout, { width: number; height: number; minWidth: number; minHeight: number }> = {
  face: { width: 500, height: 180, minWidth: 300, minHeight: 120 },
  transcript: { width: 500, height: 500, minWidth: 360, minHeight: 320 },
  settings: { width: 520, height: 600, minWidth: 420, minHeight: 480 }
}

let win: BrowserWindow | null = null
let tray: GarbisTray | null = null
let layout: Layout = 'face'
let faceSize: [number, number] | null = null // the face-only size to go back to
let quitting = false
let toldAboutTray = false

/** Headless test runs (`--ozone-platform=headless`) have no display for a tray icon. */
const trayAvailable = (): boolean => app.commandLine.getSwitchValue('ozone-platform') !== 'headless'

function createWindow(): BrowserWindow {
  const startHidden = loadSettings().startInTray && trayAvailable() // no tray: never start hidden
  const w = new BrowserWindow({
    ...LAYOUTS.face,
    title: 'Garbis',
    icon: appIcon,
    backgroundColor: BG,
    show: false,
    autoHideMenuBar: true,
    alwaysOnTop: loadSettings().alwaysOnTop,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      // Garbis keeps listening and talking while minimized or hidden in the tray.
      backgroundThrottling: false,
      // Garbis talks without a click first.
      autoplayPolicy: 'no-user-gesture-required'
    }
  })

  w.once('ready-to-show', () => {
    if (!startHidden) w.show()
  })
  w.on('close', (event) => {
    if (quitting || !tray) return // no tray: closing really closes
    event.preventDefault() // hide, don't quit: Garbis keeps listening from the tray
    w.hide()
    if (!toldAboutTray) {
      toldAboutTray = true
      tray?.noteHidden()
    }
  })
  w.on('show', refreshTray)
  w.on('hide', refreshTray)
  w.on('closed', () => {
    win = null
  })

  // No new windows; open real links in the browser instead.
  w.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://')) shell.openExternal(url)
    return { action: 'deny' }
  })
  // Never navigate the app window away from the app.
  w.webContents.on('will-navigate', (event) => event.preventDefault())

  const devUrl = process.env['ELECTRON_RENDERER_URL']
  if (!app.isPackaged && devUrl) {
    w.loadURL(devUrl)
  } else {
    w.loadFile(join(__dirname, '../renderer/index.html'))
  }
  if (!app.isPackaged && process.env['GARBIS_SCREENSHOT_DIR']) startScreenshots(w, process.env['GARBIS_SCREENSHOT_DIR'])
  return w
}

function showWindow(): void {
  if (!win) win = createWindow()
  if (win.isMinimized()) win.restore()
  win.show()
  win.focus()
}

function toggleWindow(): void {
  if (win?.isVisible()) win.hide()
  else showWindow()
}

let lastTrayState: TrayState | null = null
function refreshTray(): void {
  if (tray && lastTrayState) tray.update(lastTrayState)
}

function setLayout(next: Layout): void {
  if (!win || next === layout) return
  if (layout === 'face') faceSize = win.getSize() as [number, number]
  const size = LAYOUTS[next]
  win.setMinimumSize(size.minWidth, size.minHeight)
  if (next === 'face') {
    const [width, height] = faceSize ?? [size.width, size.height]
    win.setSize(width, height, true)
  } else {
    const [width] = win.getSize()
    win.setSize(Math.max(width, size.width), size.height, true)
  }
  layout = next
}

/** Dev only: save a PNG of the window every second (for checking the face without a screen). */
function startScreenshots(w: BrowserWindow, dir: string): void {
  mkdirSync(dir, { recursive: true })
  let n = 0
  const timer = setInterval(async () => {
    if (w.isDestroyed() || n >= 60) return clearInterval(timer)
    const click = process.env['GARBIS_SCREENSHOT_CLICK'] // e.g. "4:Settings" = click the button titled Settings at shot 4
    if (click && n === Number(click.split(':')[0])) {
      const selector = `button[title="${click.split(':').slice(1).join(':')}"]`
      await w.webContents.executeJavaScript(`document.querySelector(${JSON.stringify(selector)})?.click()`)
    }
    const image = await w.webContents.capturePage()
    writeFileSync(join(dir, `shot-${String(n++).padStart(2, '0')}.png`), image.toPNG())
  }, 1000)
}

// Only what Garbis needs: the mic, desktop audio capture and speaker choice. Everything else is refused.
const ALLOWED_PERMISSIONS = new Set<string>(['media', 'display-capture', 'speaker-selection'])

function setupPermissions(): void {
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(ALLOWED_PERMISSIONS.has(permission))
  })
  session.defaultSession.setPermissionCheckHandler((_wc, permission) => ALLOWED_PERMISSIONS.has(permission))
  if (process.platform === 'darwin' && systemPreferences.getMediaAccessStatus('microphone') !== 'granted') {
    // macOS asks once; the answer lives in System Settings > Privacy & Security > Microphone.
    void systemPreferences.askForMediaAccess('microphone')
  }
}

function sendTrayAction(action: TrayAction): void {
  win?.webContents.send('tray:action', action)
}

ipcMain.handle(
  'app:info',
  (): AppInfo => ({
    version: app.getVersion(),
    platform: process.platform,
    deviceName: hostname().replace(/\.local$/, '')
  })
)

ipcMain.handle('settings:get', (): Settings => loadSettings())

ipcMain.handle('settings:set', (_e, patch: Partial<Settings>): Settings => {
  const next = saveSettings(patch)
  win?.setAlwaysOnTop(next.alwaysOnTop)
  refreshTray()
  return next
})

ipcMain.handle('window:layout', (_e, next: Layout) => {
  if (next in LAYOUTS) setLayout(next)
})

ipcMain.handle('screen:capture', (_e, maxWidth: number) => captureMainScreen(Math.min(Math.max(Number(maxWidth) || 768, 320), 1920)))

ipcMain.on('tray:state', (_e, state: TrayState) => {
  lastTrayState = state
  tray?.update(state)
})

// One Garbis per machine: a second launch shows the existing window.
if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => showWindow())

  app.on('before-quit', () => {
    quitting = true
  })

  app.whenReady().then(() => {
    setupPermissions()
    setupDesktopAudio(session.defaultSession)
    if (process.platform === 'darwin' && !app.isPackaged) app.dock?.setIcon(nativeImage.createFromPath(appIcon))
    win = createWindow()
    if (trayAvailable()) tray = new GarbisTray({
      isWindowVisible: () => Boolean(win?.isVisible()),
      toggleWindow,
      showWindow,
      action: sendTrayAction,
      startInTray: () => loadSettings().startInTray,
      setStartInTray: (on) => {
        saveSettings({ startInTray: on })
        win?.webContents.send('settings:changed')
      },
      quit: () => app.quit()
    })
    app.on('activate', () => showWindow()) // macOS: dock icon click
  })

  // The window only hides, so this only happens when quitting.
  app.on('window-all-closed', () => app.quit())
}
