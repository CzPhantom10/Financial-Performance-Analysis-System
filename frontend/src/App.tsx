import { useEffect, useState } from 'react'
import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { ErrorBox, Loading } from './components/ui'
import { api } from './lib/api'
import type { Filters, Meta } from './lib/api'
import Executive from './pages/Executive'
import Revenue from './pages/Revenue'
import Profitability from './pages/Profitability'
import Customers from './pages/Customers'
import Products from './pages/Products'
import Anomalies from './pages/Anomalies'
import Statistics from './pages/Statistics'
import SqlLibrary from './pages/SqlLibrary'

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [filters, setFilters] = useState<Filters | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The filter defaults come from the data's own extent, so the app never
  // needs a hard-coded date range that would go stale when the data changes.
  useEffect(() => {
    api
      .meta()
      .then((m) => {
        setMeta(m)
        setFilters({
          start: m.date_range.start,
          end: m.date_range.end,
          regions: m.regions,
          categories: m.categories,
          segments: m.segments,
        })
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) {
    return (
      <div style={{ padding: 40, maxWidth: 720 }}>
        <ErrorBox message={error} />
        <p className="muted small">
          The API is not responding. Start it with <code>python -m src.api</code>{' '}
          from the project root, and make sure the pipeline has been run at least
          once (<code>python run_pipeline.py</code>).
        </p>
      </div>
    )
  }

  if (!meta || !filters) return <Loading label="Connecting to the analytics API…" />

  return (
    <Routes>
      <Route element={<Layout meta={meta} filters={filters} setFilters={setFilters} />}>
        <Route index element={<Executive filters={filters} />} />
        <Route path="revenue" element={<Revenue filters={filters} />} />
        <Route path="profitability" element={<Profitability filters={filters} />} />
        <Route path="customers" element={<Customers filters={filters} />} />
        <Route path="products" element={<Products filters={filters} />} />
        <Route path="anomalies" element={<Anomalies />} />
        <Route path="statistics" element={<Statistics />} />
        <Route path="sql" element={<SqlLibrary />} />
        <Route path="*" element={<Executive filters={filters} />} />
      </Route>
    </Routes>
  )
}
