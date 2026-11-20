/**
 * Preload: the only bridge between the sandboxed renderer and the main process.
 * Keep it narrow (ARCHITECTURE.md §11). Sandboxed, so it may only import 'electron'.
 */
import { contextBridge, ipcRenderer } from 'electron'
import type { IpcRendererEvent } from 'electron'
import type { GarbisBridge, TrayAction } from '../shared/types'

const bridge: GarbisBridge = {
  appInfo: () => ipcRenderer.invoke('app:info'),
  getSettings: () => ipcRenderer.invoke('settings:get'),
  setSettings: (patch) => ipcRenderer.invoke('settings:set', patch),
  setLayout: (layout) => ipcRenderer.invoke('window:layout', layout),
  setTrayState: (state) => ipcRenderer.send('tray:state', state),
  captureScreen: (maxWidth) => ipcRenderer.invoke('screen:capture', maxWidth),
  onTrayAction: (handler) => {
    const listener = (_e: IpcRendererEvent, action: TrayAction) => handler(action)
    ipcRenderer.on('tray:action', listener)
    return () => ipcRenderer.removeListener('tray:action', listener)
  },
  onSettingsChanged: (handler) => {
    const listener = () => handler()
    ipcRenderer.on('settings:changed', listener)
    return () => ipcRenderer.removeListener('settings:changed', listener)
  }
}

contextBridge.exposeInMainWorld('garbis', bridge)
