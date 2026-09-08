import { useEffect, useState } from 'react'
import { Bar, BarChart, YAxis } from 'recharts'
import { api } from '../lib/api'
import type { SqlResult } from '../lib/api'
import { useApi } from '../lib/useApi'
import { num, pct } from '../lib/format'
import { PALETTE } from '../lib/palette'
import { Card, DataTable, ErrorBox, Kpi, Loading, Note, PageHeader, Tabs } from '../components/ui'
import { ChartFrame, Grid, TooltipStyled, XAxisStyled } from '../components/charts'

const TABS = ['Query library', 'Data quality audit']

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
  }
  return String(value)
}

export default function SqlLibrary() {
  const [tab, setTab] = useState(TABS[0])
  const queries = useApi(() => api.sqlQueries(), [])
  const quality = useApi(() => api.dataQuality(), [])

  const [selected, setSelected] = useState<string | null>(null)
  const [result, setResult] = useState<SqlResult | null>(null)
  const [running, setRunning] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)

  useEffect(() => {
    if (!selected && queries.data?.length) setSelected(queries.data[0].name)
  }, [queries.data, selected])

  const run = async (name: string) => {
    setRunning(true)
    setRunError(null)
    try {
      setResult(await api.sqlRun(name))
    } catch (e) {
      setRunError((e as Error).message)
      setResult(null)
    } finally {
      setRunning(false)
    }
  }

  const downloadCsv = () => {
    if (!result) return
    // Quote every field and double any embedded quotes — description text in
    // these results contains commas, which would otherwise split into columns.
    const escape = (v: unknown) => `"${String(v ?? '').replace(/"/g, '""')}"`
    const csv = [
      result.columns.map(escape).join(','),
      ...result.rows.map((row) => result.columns.map((c) => escape(row[c])).join(',')),
    ].join('\n')
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
    const link = document.createElement('a')
    link.href = url
    link.download = `${result.name}.csv`
    link.click()
    URL.revokeObjectURL(url)
  }

  const spec = queries.data?.find((q) => q.name === selected)

  return (
    <>
      <PageHeader title="SQL library and data quality">
        The two things a dashboard usually hides: the SQL the numbers came from,
        and what had to be repaired before they could be trusted.
      </PageHeader>

      <Tabs tabs={TABS} active={tab} onChange={setTab} />

      {tab === 'Query library' && (
        <>
          {queries.error && <ErrorBox message={queries.error} />}
          {!queries.data ? (
            <Loading />
          ) : (
            <>
              <Note kind="info">
                {queries.data.length} analytical queries live in{' '}
                <code>sql/analysis_queries.sql</code>, written in standard SQL
                (CTEs and window functions only) so they run unchanged on SQLite,
                PostgreSQL and MySQL. They are kept in a <code>.sql</code> file
                rather than in Python string literals so they stay readable,
                diffable and runnable in any database client.
              </Note>

              <Card title="Choose a query">
                <div className="field">
                  <label className="field-label" htmlFor="query">
                    Query
                  </label>
                  <select
                    id="query"
                    value={selected ?? ''}
                    onChange={(e) => {
                      setSelected(e.target.value)
                      setResult(null)
                      setRunError(null)
                    }}
                  >
                    {queries.data.map((q) => (
                      <option key={q.name} value={q.name}>
                        {q.name.replace(/_/g, ' ')}
                      </option>
                    ))}
                  </select>
                </div>

                {spec && (
                  <>
                    <p className="small muted">{spec.description}</p>
                    <details>
                      <summary>SQL</summary>
                      <div className="details-body">
                        <pre className="sql">{spec.sql}</pre>
                      </div>
                    </details>
                    <div className="btn-row mt">
                      <button className="btn btn-primary" disabled={running}
                              onClick={() => run(spec.name)}>
                        {running ? 'Running…' : 'Run query'}
                      </button>
                      {result && (
                        <button className="btn" onClick={downloadCsv}>
                          Download CSV
                        </button>
                      )}
                    </div>
                  </>
                )}
              </Card>

              {runError && <div className="mt"><ErrorBox message={runError} /></div>}

              {result && (
                <Card className="mt" title={`Result — ${result.name.replace(/_/g, ' ')}`}
                      subtitle={`${num(result.row_count)} rows x ${result.columns.length} columns${
                        result.truncated ? ' (showing the first 500)' : ''}`}>
                  <div className="table-wrap">
                    <div className="table-scroll">
                      <table>
                        <thead>
                          <tr>
                            {result.columns.map((c) => (
                              <th key={c} className="num">{c}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {result.rows.map((row, i) => (
                            <tr key={i}>
                              {result.columns.map((c) => (
                                <td key={c} className={typeof row[c] === 'number' ? 'num' : ''}>
                                  {formatCell(row[c])}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </Card>
              )}
            </>
          )}
        </>
      )}

      {tab === 'Data quality audit' && (
        <>
          {quality.error && <ErrorBox message={quality.error} />}
          {!quality.data ? (
            <Loading />
          ) : (
            (() => {
              const s = quality.data.summary
              const reasons = Object.entries(s.rejection_reasons)
                .map(([reason, rows]) => ({
                  reason: reason.replace(/_/g, ' '),
                  rows,
                }))
                .sort((a, b) => a.rows - b.rows)
              const byStage = Object.entries(
                quality.data.steps.reduce<Record<string, number>>((acc, step) => {
                  acc[step.step] = (acc[step.step] ?? 0) + step.rows_affected
                  return acc
                }, {}),
              )
                .map(([stage, rows]) => ({ stage, rows }))
                .sort((a, b) => a.rows - b.rows)

              return (
                <>
                  <div className="kpi-row">
                    <Kpi label="Raw rows" value={num(s.raw_rows)} />
                    <Kpi label="Loaded rows" value={num(s.clean_rows)}
                         hint={`${s.retention_rate_pct}% retained`} />
                    <Kpi label="Duplicates removed" value={num(s.rows_removed_as_duplicates)}
                         higherIsBetter={false} />
                    <Kpi label="Quarantined" value={num(s.rejected_rows)}
                         higherIsBetter={false} />
                    <Kpi label="Retention" value={pct(s.retention_rate_pct)} />
                  </div>

                  <Note kind="danger">
                    <strong>
                      {num(s.rows_with_reconciliation_error)} rows (
                      {pct((s.rows_with_reconciliation_error / s.clean_rows) * 100)}) arrived
                      with a <code>revenue</code> or <code>profit</code> value that
                      did not reconcile with its own components.
                    </strong>{' '}
                    The pipeline treats the components as authoritative and
                    recomputes the money from{' '}
                    <code>quantity × unit_price × (1 − discount)</code>. Every
                    figure in this dashboard is derived that way rather than from a
                    field that had already drifted. Had the reported values been
                    trusted as they arrived, the revenue total would have been
                    wrong by an amount no downstream reconciliation would have
                    caught.
                  </Note>

                  <div className="grid grid-2">
                    <Card
                      title="Why rows were quarantined"
                      note="Quarantined rows are written to data/processed/transactions_rejected.csv with a reason code rather than deleted, so the decision is reviewable and reversible."
                    >
                      <ChartFrame height={300}>
                        <BarChart data={reasons} layout="vertical"
                                  margin={{ top: 8, right: 34, left: 4, bottom: 4 }}>
                          <Grid />
                          <XAxisStyled type="number" />
                          <YAxis type="category" dataKey="reason" width={170}
                                 stroke="var(--text-faint)" fontSize={10}
                                 tickLine={false} axisLine={false} />
                          <TooltipStyled />
                          <Bar dataKey="rows" name="Rows" fill={PALETTE[1]} radius={[0, 3, 3, 0]} />
                        </BarChart>
                      </ChartFrame>
                    </Card>

                    <Card
                      title="Rows touched by pipeline stage"
                      note="The parse stage touches every row by definition — it is the type-coercion pass, not a repair."
                    >
                      <ChartFrame height={300}>
                        <BarChart data={byStage} layout="vertical"
                                  margin={{ top: 8, right: 34, left: 4, bottom: 4 }}>
                          <Grid />
                          <XAxisStyled type="number" />
                          <YAxis type="category" dataKey="stage" width={110}
                                 stroke="var(--text-faint)" fontSize={11}
                                 tickLine={false} axisLine={false} />
                          <TooltipStyled />
                          <Bar dataKey="rows" name="Rows" fill={PALETTE[0]} radius={[0, 3, 3, 0]} />
                        </BarChart>
                      </ChartFrame>
                    </Card>
                  </div>

                  <Card
                    className="mt"
                    title="Full cleaning audit log"
                    subtitle="Each step records what it changed, so the cleaning is reviewable rather than a black box"
                  >
                    <DataTable
                      scroll
                      rowKey={(r, i) => `${r.step}-${i}`}
                      rows={quality.data.steps}
                      columns={[
                        { key: 'stage', label: 'Stage', render: (r) => r.step },
                        { key: 'action', label: 'Action',
                          render: (r) => <span style={{ whiteSpace: 'normal' }}>{r.detail}</span> },
                        { key: 'rows', label: 'Rows', numeric: true,
                          render: (r) => num(r.rows_affected) },
                      ]}
                    />
                  </Card>
                </>
              )
            })()
          )}
        </>
      )}
    </>
  )
}
