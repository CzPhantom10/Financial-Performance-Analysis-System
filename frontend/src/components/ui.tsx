/* Small shared presentation components. */
import type { ReactNode } from 'react'
import { deltaClass } from '../lib/palette'
import { signedPct } from '../lib/format'

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="page-header">
      <h1>{title}</h1>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Card({
  title,
  subtitle,
  note,
  children,
  className = '',
}: {
  title?: string
  subtitle?: string
  note?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <div className={`card ${className}`}>
      {title && <div className="card-title">{title}</div>}
      {subtitle && <div className="card-sub">{subtitle}</div>}
      {children}
      {note && <div className="card-note">{note}</div>}
    </div>
  )
}

export function Kpi({
  label,
  value,
  delta,
  deltaSuffix = '%',
  higherIsBetter = true,
  hint,
}: {
  label: string
  value: string
  delta?: number | null
  deltaSuffix?: string
  higherIsBetter?: boolean
  hint?: string
}) {
  const tone = deltaClass(delta, higherIsBetter)
  return (
    <div className="kpi" title={hint}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {delta !== undefined && delta !== null && !Number.isNaN(delta) ? (
        <div className={`kpi-delta ${tone}`}>
          {deltaSuffix === '%'
            ? signedPct(delta)
            : `${delta >= 0 ? '+' : ''}${delta.toFixed(2)}${deltaSuffix}`}
        </div>
      ) : (
        <div className="kpi-delta flat">—</div>
      )}
    </div>
  )
}

export function Note({
  kind = 'info',
  children,
}: {
  kind?: 'info' | 'warn' | 'danger' | 'ok'
  children: ReactNode
}) {
  return <div className={`note ${kind}`}>{children}</div>
}

export function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="loading">{label}</div>
}

export function ErrorBox({ message }: { message: string }) {
  return (
    <div className="error-box">
      <strong>Could not load this view.</strong>
      <div className="mt small">{message}</div>
    </div>
  )
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: string[]
  active: string
  onChange: (tab: string) => void
}) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((tab) => (
        <button
          key={tab}
          role="tab"
          aria-selected={tab === active}
          className={`tab ${tab === active ? 'active' : ''}`}
          onClick={() => onChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}

export interface Column<T> {
  key: string
  label: string
  numeric?: boolean
  render: (row: T) => ReactNode
}

export function DataTable<T>({
  columns,
  rows,
  scroll = false,
  rowKey,
  onRowClick,
  selectedKey,
}: {
  columns: Column<T>[]
  rows: T[]
  scroll?: boolean
  rowKey: (row: T, index: number) => string
  onRowClick?: (row: T) => void
  selectedKey?: string
}) {
  const body = (
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.key} className={c.numeric ? 'num' : ''}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => {
          const key = rowKey(row, index)
          return (
            <tr
              key={key}
              className={`${onRowClick ? 'clickable' : ''} ${
                selectedKey === key ? 'selected' : ''
              }`}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={c.numeric ? 'num' : ''}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          )
        })}
      </tbody>
    </table>
  )
  return (
    <div className="table-wrap">{scroll ? <div className="table-scroll">{body}</div> : body}</div>
  )
}
