/* Chart colours.
 *
 * Recharts needs concrete colour values rather than CSS variables, so the
 * palette lives here as literals. Every colour was picked to stay legible on
 * both the light and dark surfaces and to remain distinguishable under the
 * common forms of colour vision deficiency - which rules out the usual
 * red/green pairing for categorical series.
 */

export const PALETTE = [
  '#4a82b8', // blue
  '#e08a3c', // amber
  '#4c9f70', // green
  '#b0446c', // magenta
  '#7c6d9e', // violet
  '#c2a03a', // gold
  '#5fa0ae', // teal
  '#8c6d4f', // brown
]

export const ACCENT = '#4a82b8'
export const GOOD = '#3d9970'
export const BAD = '#cf4b3c'
export const WARN = '#d68910'
export const NEUTRAL = '#8b93a1'

export const SEVERITY_COLOR: Record<string, string> = {
  Critical: '#cf4b3c',
  High: '#d68910',
  Medium: '#4a82b8',
  Low: '#8b93a1',
}

export const SEVERITY_ORDER = ['Critical', 'High', 'Medium', 'Low']

/** Colour a delta by whether it is *good news*, not by its sign.
 *
 * A rise in cost and a rise in revenue are both positive numbers and mean
 * opposite things, so direction alone cannot pick the colour.
 */
export function deltaClass(
  change: number | null | undefined,
  higherIsBetter: boolean,
): 'good' | 'bad' | 'flat' {
  if (change === null || change === undefined || Number.isNaN(change) || change === 0) {
    return 'flat'
  }
  return change > 0 === higherIsBetter ? 'good' : 'bad'
}
