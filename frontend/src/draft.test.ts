import { describe, expect, it } from 'vitest'
import { changePick, chartPoints, unknownPick } from './draft'
import type { Draft } from './types'
describe('visible manual draft state', () => {
  const draft: Draft = { allies: Array.from({ length: 5 }, unknownPick), enemies: Array.from({ length: 5 }, unknownPick), side: 'blue', region: 'EUW1', queue: 420, patch: '' }
  it('replaces a hover without touching unknown slots or mutating the prior draft', () => {
    const hover = changePick(draft, 'allies', 3, { champion_id: 222, state: 'hover', role: '' })
    const replaced = changePick(hover, 'allies', 3, { champion_id: 119, state: 'locked', role: '' })
    expect(draft.allies[3].champion_id).toBe(0)
    expect(replaced.allies[3]).toEqual({ champion_id: 119, state: 'locked', role: '' })
    expect(replaced.enemies.every(p => p.champion_id === 0)).toBe(true)
  })
  it('never draws a fabricated prediction when the model is missing', () => {
    expect(chartPoints([{ time: 0, probability: null, confirmed: null, known: 0, tentative: false, change: null }])).toBe('')
  })
})
