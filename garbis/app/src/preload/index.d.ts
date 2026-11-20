import type { GarbisBridge } from '../shared/types'

declare global {
  interface Window {
    garbis: GarbisBridge
  }
}
