import { describe, expect, it } from 'vitest'
import { DESKTOP_TAIL_MS, desktopGated } from './echo'

describe('desktop echo gating', () => {
  it('blocks desktop audio while Garbis is playing', () => {
    expect(desktopGated(true, 0, 10_000)).toBe(true)
  })

  it('blocks it for the tail after he stops, then lets it through', () => {
    const end = 10_000
    expect(desktopGated(false, end, end + 1)).toBe(true)
    expect(desktopGated(false, end, end + DESKTOP_TAIL_MS - 1)).toBe(true)
    expect(desktopGated(false, end, end + DESKTOP_TAIL_MS)).toBe(false)
  })

  it('lets audio through when he has never spoken', () => {
    expect(desktopGated(false, 0, 50)).toBe(false)
  })
})
