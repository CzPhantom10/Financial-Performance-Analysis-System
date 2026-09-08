/* Number formatting shared by every chart, tile and table. */

/** Abbreviate currency, but never at the cost of digits the reader wants.
 *
 * The 'k' cutoff sits at 10,000 rather than 1,000 deliberately: an average
 * order value of $6,617 rendered as "$7k" throws away the precision that made
 * the number worth showing.
 */
export function money(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  const magnitude = Math.abs(value)
  if (magnitude >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(decimals)}B`
  if (magnitude >= 1_000_000) return `$${(value / 1_000_000).toFixed(decimals)}M`
  if (magnitude >= 10_000) return `$${Math.round(value / 1_000).toLocaleString()}k`
  return `$${Math.round(value).toLocaleString()}`
}

export function moneyFull(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `$${value.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`
}

export function pct(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value.toFixed(decimals)}%`
}

export function signedPct(value: number | null | undefined, decimals = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return `${value >= 0 ? '+' : ''}${value.toFixed(decimals)}%`
}

export function num(value: number | null | undefined, decimals = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })
}

/** Scientific notation for p-values, which span many orders of magnitude. */
export function pValue(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  if (value === 0) return '< 1e-300'
  if (value < 0.001) return value.toExponential(2)
  return value.toFixed(4)
}

/** "2024-03-01" -> "Mar 2024", without constructing a Date.
 *
 * Parsing the string as a Date would apply the browser's timezone and can
 * shift a month-start backwards into the previous month.
 */
export function monthLabel(iso: string): string {
  if (!iso) return ''
  const names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const [year, month] = iso.slice(0, 10).split('-')
  const index = Number(month) - 1
  return index >= 0 && index < 12 ? `${names[index]} ${year}` : iso.slice(0, 7)
}

export function shortMonth(iso: string): string {
  const label = monthLabel(iso)
  const [m, y] = label.split(' ')
  return y ? `${m} ${y.slice(2)}` : label
}

/** Compact axis ticks: 12500000 -> "12.5M". */
export function axisMoney(value: number): string {
  const magnitude = Math.abs(value)
  if (magnitude >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`
  if (magnitude >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (magnitude >= 1_000) return `${Math.round(value / 1_000)}k`
  return String(Math.round(value))
}

export function severityClass(severity: string): string {
  return severity.toLowerCase()
}
