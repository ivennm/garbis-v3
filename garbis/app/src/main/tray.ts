/**
 * Tray / menu bar icon (M4). Garbis keeps listening while the window is hidden, so the tray is
 * where you show him again, switch modes, mute, and quit.
 */
import { readFileSync } from 'node:fs'
import { Menu, Tray, nativeImage } from 'electron'
import type { MenuItemConstructorOptions } from 'electron'
import trayColor from '../../resources/tray.png?asset'
import trayTemplate from '../../resources/trayTemplate.png?asset'
import trayTemplate2x from '../../resources/trayTemplate@2x.png?asset'
import type { TrayAction, TrayState } from '../shared/types'

export interface TrayHandlers {
  isWindowVisible(): boolean
  toggleWindow(): void
  showWindow(): void
  action(action: TrayAction): void
  startInTray(): boolean
  setStartInTray(on: boolean): void
  quit(): void
}

const INITIAL: TrayState = {
  status: 'Starting…',
  online: false,
  mode: 'low',
  modeLoading: false,
  muted: false,
  desktopAudio: true,
  screenVision: true,
  transcriptOpen: false
}

function icon(): Electron.NativeImage {
  if (process.platform === 'darwin') {
    // black + alpha "template" image: macOS tints it for light/dark menu bars
    const img = nativeImage.createFromPath(trayTemplate)
    img.addRepresentation({ scaleFactor: 2, buffer: readFileSync(trayTemplate2x) })
    img.setTemplateImage(true)
    return img
  }
  return nativeImage.createFromPath(trayColor)
}

export class GarbisTray {
  private readonly tray: Tray
  private state: TrayState = INITIAL

  constructor(private readonly h: TrayHandlers) {
    this.tray = new Tray(icon())
    // Windows/Linux: a left click shows/hides Garbis; the menu is on right click.
    // macOS: any click opens the menu, as menu bar icons do.
    if (process.platform !== 'darwin') this.tray.on('click', () => h.toggleWindow())
    this.render()
  }

  update(state: TrayState): void {
    this.state = state
    this.render()
  }

  /** Windows: tell the user once that closing the window didn't quit Garbis. */
  noteHidden(): void {
    if (process.platform === 'win32') {
      this.tray.displayBalloon({
        title: 'Garbis is still listening',
        content: 'He lives in the tray now. Right-click the icon to quit.'
      })
    }
  }

  private render(): void {
    const s = this.state
    const h = this.h
    const canSwitch = s.online && !s.modeLoading
    const modeLabel = s.mode.toUpperCase() + (s.modeLoading ? ' (loading…)' : '')
    this.tray.setToolTip(`Garbis · ${s.status} · ${modeLabel}`)

    const items: MenuItemConstructorOptions[] = [
      { label: `Garbis: ${s.status}`, enabled: false },
      {
        label: h.isWindowVisible() ? 'Hide Garbis' : 'Show Garbis',
        click: () => {
          h.toggleWindow()
          this.render()
        }
      },
      { type: 'separator' },
      {
        label: 'Low mode (quick and funny)',
        type: 'radio',
        checked: s.mode === 'low',
        enabled: canSwitch,
        click: () => h.action('mode:low')
      },
      {
        label: 'High mode (thinks harder)',
        type: 'radio',
        checked: s.mode === 'high',
        enabled: canSwitch,
        click: () => h.action('mode:high')
      },
      { type: 'separator' },
      { label: 'Mute mic', type: 'checkbox', checked: s.muted, click: () => h.action('toggle-mute') },
      {
        label: 'Hear desktop audio (guests)',
        type: 'checkbox',
        checked: s.desktopAudio,
        click: () => h.action('toggle-desktop')
      },
      {
        label: 'Garbis can see my screen',
        type: 'checkbox',
        checked: s.screenVision,
        click: () => h.action('toggle-screen')
      },
      {
        label: 'Show transcript',
        type: 'checkbox',
        checked: s.transcriptOpen,
        click: () => {
          h.showWindow()
          h.action('toggle-transcript')
        }
      },
      { type: 'separator' },
      {
        label: 'Start in the tray',
        type: 'checkbox',
        checked: h.startInTray(),
        click: (item) => h.setStartInTray(item.checked)
      },
      { label: 'Quit Garbis', click: () => h.quit() }
    ]
    this.tray.setContextMenu(Menu.buildFromTemplate(items))
  }
}
