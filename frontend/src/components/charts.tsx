/* Recharts wrappers carrying the shared styling.
 *
 * Charts are configured once here rather than per page so axes, gridlines,
 * tooltips and margins stay identical across the dashboard - the reader learns
 * to read one chart, not eight.
 */
import type { ReactNode } from 'react'
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

export const AXIS = {
  stroke: 'var(--text-faint)',
  fontSize: 11,
  tickLine: false,
  axisLine: false,
}

export function ChartFrame({ height = 300, children }: { height?: number; children: ReactNode }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      {children as React.ReactElement}
    </ResponsiveContainer>
  )
}

export function Grid() {
  return <CartesianGrid stroke="var(--grid)" strokeDasharray="3 3" vertical={false} />
}

export function XAxisStyled(props: Record<string, unknown>) {
  return <XAxis {...AXIS} {...props} />
}

export function YAxisStyled(props: Record<string, unknown>) {
  return <YAxis {...AXIS} width={62} {...props} />
}

export function LegendStyled() {
  return <Legend wrapperStyle={{ fontSize: 12, paddingTop: 6 }} iconType="circle" iconSize={8} />
}

export interface TooltipEntry {
  name?: string
  value?: number | string
  color?: string
  dataKey?: string | number
}

/** Tooltip that formats each series with its own formatter.
 *
 * Recharts' default renders every series with one formatter, which is wrong
 * as soon as a chart mixes dollars with percentages - the dual-axis charts
 * here all do.
 */
export function makeTooltip(
  labelFormat: (label: string) => string,
  formatters: Record<string, (value: number) => string>,
  fallback: (value: number) => string = (v) => String(v),
) {
  return function CustomTooltip({
    active,
    payload,
    label,
  }: {
    active?: boolean
    payload?: TooltipEntry[]
    label?: string | number
  }) {
    if (!active || !payload?.length) return null
    return (
      <div className="chart-tooltip">
        <div className="tt-label">{labelFormat(String(label ?? ''))}</div>
        {payload.map((entry, index) => {
          const key = String(entry.dataKey ?? entry.name ?? index)
          const format = formatters[key] ?? fallback
          const value = typeof entry.value === 'number' ? format(entry.value) : entry.value
          return (
            <div className="tt-row" key={key + index}>
              <span style={{ color: entry.color }}>{entry.name}</span>
              <b>{value ?? '—'}</b>
            </div>
          )
        })}
      </div>
    )
  }
}

export function TooltipStyled(props: Record<string, unknown>) {
  return (
    <Tooltip
      cursor={{ fill: 'var(--surface-2)', opacity: 0.55 }}
      contentStyle={{
        background: 'var(--surface)',
        border: '1px solid var(--border-strong)',
        borderRadius: 8,
        fontSize: 12,
      }}
      labelStyle={{ color: 'var(--text)', fontWeight: 600 }}
      itemStyle={{ color: 'var(--text-muted)' }}
      {...props}
    />
  )
}
