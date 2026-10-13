import type { Draft, History, Pick } from './types'
export const unknownPick = (): Pick => ({ champion_id: 0, state: 'unknown', role: '' })
export function changePick(draft: Draft, team: 'allies' | 'enemies', index: number, pick: Pick): Draft {
  return { ...draft, [team]: draft[team].map((old, i) => i === index ? pick : old) }
}
export function chartPoints(history: History[], width = 620, height = 120) {
  const valid = history.filter((h): h is History & { probability: number } => h.probability !== null)
  if (!valid.length) return ''
  return valid.map((h, i) => `${24 + i / Math.max(1, valid.length - 1) * (width - 48)},${16 + (1 - h.probability) * (height - 32)}`).join(' ')
}
