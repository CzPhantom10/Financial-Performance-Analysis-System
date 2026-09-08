/* App shell: navigation, the global filter panel and the theme toggle.
 *
 * Filters live at this level rather than inside each page, so a selection
 * survives navigation instead of resetting every time the user moves between
 * Revenue and Profitability.
 */
import { useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import type { Filters, Meta } from '../lib/api'
import { num } from '../lib/format'

const PAGES = [
  { path: '/', label: 'Executive overview', end: true },
  { path: '/revenue', label: 'Revenue analysis' },
  { path: '/profitability', label: 'Profitability' },
  { path: '/customers', label: 'Customers' },
  { path: '/products', label: 'Products' },
  { path: '/anomalies', label: 'Anomaly monitor' },
  { path: '/statistics', label: 'Statistical analysis' },
  { path: '/sql', label: 'SQL & data quality' },
]

type Theme = 'light' | 'dark' | 'system'

function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem('theme') as Theme) || 'system'
    } catch {
      // Private windows and blocked site data make localStorage throw on read.
      return 'system'
    }
  })

  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
    try {
      localStorage.setItem('theme', theme)
    } catch {
      /* preference simply will not persist; the UI still works */
    }
  }, [theme])

  return [theme, setTheme]
}

function ChipGroup({
  options,
  selected,
  onToggle,
  onAll,
}: {
  options: string[]
  selected: string[]
  onToggle: (value: string) => void
  onAll: () => void
}) {
  const allOn = selected.length === options.length
  return (
    <>
      <div className="chips">
        {options.map((option) => (
          <button
            key={option}
            className={`chip ${selected.includes(option) ? 'on' : ''}`}
            onClick={() => onToggle(option)}
          >
            {option}
          </button>
        ))}
      </div>
      <button className="chip" style={{ marginTop: 6 }} onClick={onAll}>
        {allOn ? 'Clear all' : 'Select all'}
      </button>
    </>
  )
}

export default function Layout({
  meta,
  filters,
  setFilters,
}: {
  meta: Meta
  filters: Filters
  setFilters: (f: Filters) => void
}) {
  const [theme, setTheme] = useTheme()

  const toggle = (key: 'regions' | 'categories' | 'segments', value: string) => {
    const current = filters[key]
    setFilters({
      ...filters,
      [key]: current.includes(value)
        ? current.filter((v) => v !== value)
        : [...current, value],
    })
  }

  const selectAll = (key: 'regions' | 'categories' | 'segments', options: string[]) => {
    setFilters({
      ...filters,
      [key]: filters[key].length === options.length ? [] : options,
    })
  }

  const reset = () =>
    setFilters({
      start: meta.date_range.start,
      end: meta.date_range.end,
      regions: meta.regions,
      categories: meta.categories,
      segments: meta.segments,
    })

  const isFiltered =
    filters.start !== meta.date_range.start ||
    filters.end !== meta.date_range.end ||
    filters.regions.length !== meta.regions.length ||
    filters.categories.length !== meta.categories.length ||
    filters.segments.length !== meta.segments.length

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Financial Analytics</div>
        <div className="brand-sub">
          Revenue, profitability, cost and anomaly monitoring over{' '}
          {num(meta.transactions)} transactions
        </div>

        <nav className="nav">
          {PAGES.map((page) => (
            <NavLink key={page.path} to={page.path} end={page.end}>
              {page.label}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-section">
          <div className="sidebar-label">Filters</div>

          <div className="field">
            <label className="field-label" htmlFor="start">
              From
            </label>
            <input
              id="start"
              type="date"
              value={filters.start}
              min={meta.date_range.start}
              max={meta.date_range.end}
              onChange={(e) => setFilters({ ...filters, start: e.target.value })}
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="end">
              To
            </label>
            <input
              id="end"
              type="date"
              value={filters.end}
              min={meta.date_range.start}
              max={meta.date_range.end}
              onChange={(e) => setFilters({ ...filters, end: e.target.value })}
            />
          </div>

          <div className="field">
            <span className="field-label">Region</span>
            <ChipGroup
              options={meta.regions}
              selected={filters.regions}
              onToggle={(v) => toggle('regions', v)}
              onAll={() => selectAll('regions', meta.regions)}
            />
          </div>

          <div className="field">
            <span className="field-label">Product category</span>
            <ChipGroup
              options={meta.categories}
              selected={filters.categories}
              onToggle={(v) => toggle('categories', v)}
              onAll={() => selectAll('categories', meta.categories)}
            />
          </div>

          <div className="field">
            <span className="field-label">Customer segment</span>
            <ChipGroup
              options={meta.segments}
              selected={filters.segments}
              onToggle={(v) => toggle('segments', v)}
              onAll={() => selectAll('segments', meta.segments)}
            />
          </div>

          {isFiltered && (
            <button className="btn" onClick={reset} style={{ marginTop: 4 }}>
              Reset filters
            </button>
          )}
        </div>

        <div className="sidebar-section">
          <div className="sidebar-label">Appearance</div>
          <div className="chips">
            {(['light', 'dark', 'system'] as Theme[]).map((option) => (
              <button
                key={option}
                className={`chip ${theme === option ? 'on' : ''}`}
                onClick={() => setTheme(option)}
              >
                {option}
              </button>
            ))}
          </div>
        </div>

        <div className="sidebar-section">
          <p className="faint small" style={{ margin: 0 }}>
            Filters apply to every view built from the transaction ledger. The
            statistical tests, the STL decomposition and the anomaly monitor are
            computed on the full dataset by the Python pipeline and are labelled
            as unfiltered where they appear.
          </p>
          <p className="faint small" style={{ marginBottom: 0 }}>
            Aggregation runs in SQL. No machine learning — every finding comes
            from classical statistics and queries.
          </p>
        </div>
      </aside>

      <main className="main">
        <Outlet />
      </main>
    </div>
  )
}
