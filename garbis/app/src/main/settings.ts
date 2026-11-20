/** settings.json in Electron's userData folder. Written atomically (temp file + rename). */
import { existsSync, readFileSync, renameSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import { app } from 'electron'
import { DEFAULT_SETTINGS, sanitizeSettings } from '../shared/settings'
import type { Settings } from '../shared/types'

let current: Settings | null = null

const file = (): string => join(app.getPath('userData'), 'settings.json')

export function loadSettings(): Settings {
  if (current) return current
  try {
    current = existsSync(file()) ? sanitizeSettings(JSON.parse(readFileSync(file(), 'utf8'))) : { ...DEFAULT_SETTINGS }
  } catch (e) {
    console.warn('settings.json unreadable, using defaults:', e)
    current = { ...DEFAULT_SETTINGS }
  }
  return current
}

export function saveSettings(patch: Partial<Settings>): Settings {
  current = sanitizeSettings(patch, loadSettings())
  const tmp = file() + '.tmp'
  writeFileSync(tmp, JSON.stringify(current, null, 2), 'utf8')
  renameSync(tmp, file())
  return current
}
